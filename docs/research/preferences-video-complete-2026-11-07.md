# Video 5/5.5: complete-file Preferences research inventory

Research date: 2026-11-07. This is a complete **byte accounting**, not a claim
that every preference has been decoded. Latest RetailOS 1.3 for updater families
13, 20 and 25 remains the scope. Every file byte belongs to a named or partially
identified field, or an explicit unresolved interval. No unreferenced or
default-zero byte is declared padding.

The major new distinction is that `Preferences` stores the **next alarm selected
from the Clock collection**, while individual city clocks and their alarms live
in `iPod_Control/Device/clock`. A Preferences alarm-minute edit therefore cannot
be described as editing a selected persistent Clock alarm. The current firmware
both produces and consumes this projection; it is not dead legacy data.

## Inputs, evidence and reproducibility

| Updater | Latest release | OSOS bytes | SHA-256 |
| --- | --- | ---: | --- |
| 13 | 1.3 | 7,559,680 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| 20 | 1.3 | 7,559,680 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| 25 | 1.3 | 7,561,216 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` |

13 and 20 are identical complete images. 25 has that exact prefix followed by
1,536 zero bytes. Each complete input is independently checked and loaded; code
equality does not eliminate hardware-dependent branches. The
[previous qualification](preferences-mini-video-writes-2026-11-07.md) links the
catalog provenance and runtime-map evidence. This pass executes the same original
startup relocation at `0x83848`, using the pinned helper, before its native tests.

The [final native receipt][receipt] contains **393 passing cases, 131 per input**,
and hashes **1,817 executed four-byte instructions per input**. It records source
hashes, helper hashes, adapters, defaults and each case. New probes cover complete
Preferences serialization for Backlight, Contacts, Clock display, Audiobooks,
Brightness, Volume Limit, main-menu masks, artwork/video booleans, EQ counted
strings, Photo controls and Voice Memo quality; current-loader forced flags;
hardware-dependent Search/brightness behavior; and native Clock record framing.
The earlier four-control, language, retention and invalid-header tests remain
separately qualified by the previous report; their counts are not added again.

The [native script][probe] hash is
`dd787bc1a3e1e5433e82d9a4d131ee4cda03beaaf6403d2910f5ab4683287a58`.
The final receipt hash is
`dfb5b8c8c14da9917fb6987f191794f51f4c9f71687d4789eb406042b45d4681`.
Run from the sibling firmware lab, using new output directories:

```powershell
uv run scripts/research_video_preferences_inventory.py --output artifacts/NEW-video-survey
uv run scripts/inventory_preferences_video_full.py --survey artifacts/NEW-video-survey --output artifacts/NEW-video-fields
```

Both scripts pass Ruff formatting and linting through the application's UV
environment. The [inventory][inventory] records its builder and survey hashes,
and hashes all files in the six new read-only static exports. It also verifies
every exported instruction byte against the original OSOS. The owner-pointer
search produced 211 functions; its `+0xCA0` hits are search candidates, not proof
that every hit belongs to Preferences. The subsequent exact-entry exports bind
the complete original ROM and leave Ghidra projects unsaved. No firmware source
bytes, physical device, shared application code or device files were changed.

Filesystem services, notification delivery, selected hardware queries, unrelated
playback services and UI framework calls are adapted. Setting tests compare the
**entire saved file**, permitting differences only in the documented field.
Clock record tests adapt stream I/O and city lookup, while executing the original
record reader/writer and byte-framing helpers. These tests do not establish a
complete boot, physical acceptance, audible output or USB adoption.

## Framing, coverage and lifecycle

Offsets below are relative to byte zero of
`iPod_Control/Device/Preferences`. The file is **2,924 / `0xB6C` bytes**, with
LE u32 version **57 / `0x39`** at zero. The serialized owner payload starts at
**owner + 8**; owner offsets must not be reported as file offsets.

| Each of 13, 20 and 25 | Bytes |
| --- | ---: |
| Entire file | 2,924 |
| Assigned to 52 named/partially identified fields or structures | 625 |
| Resolved stated representation and meaning | 548 |
| Unmapped | 2,299 |
| Unresolved, including entire partially understood fields | 2,376 |
| Proved padding | 0 |

The 510-byte EQ name allocation accounts for most resolved bytes; this does not
represent hundreds of independent preferences. A masked word remains entirely
unresolved in this metric whenever any bits are unexplained. The machine
inventory contains a gap-free partition, integer offsets/sizes, defaults, types,
UI domains, native domains, representable domains, effects, coupled fields and
separate unresolved intervals. Candidate Photo/Radio numeric label associations
are explicitly marked provisional rather than silently promoted to proof.

The large unresolved intervals include file `[0x19,0x8A)`, `[0x92,0x8E0)` and
`[0x8E1,0x8EA)`, as well as smaller gaps and `[0xB55,0xB60)`. Whole-file default
zeroing and preservation do not identify their structures. Future investigation
must follow pointer-derived/array consumers as well as simple scalar accessors.

Defaults `0xF3DC0`, reader `0xE1B64`, loader `0xAF698`, owner constructor
`0xA25B4`, and dirty save `0xBBF1C` retain their prior qualification. The reset
word at file 4 requests defaults when nonzero. Current loading also **forces
bytes `0x91`, `0xB0A` and `0xB0B` to 1**. The new probes explicitly start each at
zero and compare the complete result. Their feature meanings remain unresolved.

Default payloads under the recorded adapters are identical, SHA-256
`7f4b6986904c24f76b628ca106e1bd5d3a0a67918238ffe62954a1204ba5149a`.
Region helpers are adapted to zero and brightness capability to 100 for this
fixture; this is not a claim of identical physical defaults on every Video.

Full saves overlay live volume words at 8/12 and EQ state, then copy retained
owner bytes. A dirty firmware save can overwrite a Host file patch. Actual
USB/eject reconstruction and a reliable physical adoption sequence remain open.
The new Clock evidence adds a separate semantic limit: modifying the pending
projection is not equivalent to editing the independently persisted collection.

## Additional scalar preferences

All multi-byte scalar fields are little-endian. Defaults below refer to the
recorded fixture unless a hardware dependency is stated.

| Field | Storage/default | Offered or verified domain and effect |
| --- | --- | --- |
| Backlight Timer `0xAF0` | u32 / 4 | `0` Off, `2` 2 seconds, `3` 5 seconds, `4` 10 seconds, `5` 15 seconds, `6` 20 seconds, `8` Always On. These are selectors. |
| Contacts Sort `0xB0C` | u16 / 0 | `0` First Last, `1` Last, First. |
| Contacts Display `0xB14` | u16 / 0 | Same labels, independent of sort. |
| Clock display `0xB1C` | u32 / 0 | Bit 0 selects 12/24-hour; bit 1 enables Time in Title. Upper 30 bits preserved and unexplained. |
| Audiobooks `0xB38` | **i8** / 0 | `-1` Slower, `0` Normal, `1` Faster. `FF` is signed −1. |
| Alternate backlight `0xB4A` | i8 / 7 | `0` Always Off, `7` While Playing, `8` Always On, `9` On Keypress; separate property `0x6004`, not the ordinary timer. |
| Large Album Art `0xB4B` | u8 / 0 | `0` Off, `1` On. Exact label from menu `0x6022`, private string `0xFFFFFF3A`; rendering consumer still open. |
| Property `0x60B8`, file `0xB4C` | u8 / 1 | Native Off/On toggle; calls `0x1BFEF0/0x1BFD18/0x1BFB94`; precise feature still unknown. |
| Widescreen `0xB4D` | u8 / 1 | `0` Off, `1` On, explicitly labelled in Video Settings menu `0x5601`. |
| Volume Limit `0xB50` | **u32** / 100 | Native callback accepts the injected full 32-bit values without clamping; complete UI/locking/enforcement rules remain open. Not a historical byte constrained to `0..64`. |
| Brightness `0xB54` | u8 / hardware-dependent | UI installs `0..100` bounds. Raw callback stores the low byte: injected 256 becomes 0. This does not make all 256 patterns valid slider choices. |
| Voice Memo Quality `0xB60` | u8 / 1 | `0` Low, `1` High; original label getter, toggle and complete save tested. |

Settings dispatcher `0x1919D8`, main menu resource records, and native setters
support these bindings. Backlight submenu `0xFFFFFF76` actually offers the stated
sparse values; 1 and 7 are absent. Positive string IDs alone give an incomplete
picture because many menu labels use negative private IDs.

Brightness provider `0x9BCB4` returns 100 when the hardware word is at most
`0xB0010`, and 42 otherwise. Defaults choose saved 100 for the first result and
saved 50 otherwise. Native cases cover `A0000`, `B0000`, `B0010`, `B0011` and
`C0000`; these synthetic hardware words are **not** assigned marketing model
names. Volume Limit also has an external provider/locking branch in `0x193498`
and Settings refresh `0x193B90`, so a raw setter alone is insufficient for a
complete volume-safety model.

Voice Memo getter `0x1C1D24` uses property `0x3D1D`; resources `0x3D1E/0x3D1F`
say Low/High. Toggle `0x1C1C9C` calls setter `0xB405C`. Recording setup fragment
`0x1C1508` statically selects a **22,050** rate word for Low and **44,100** for
High, with accompanying words 1/1/2 or 2/2/4. Those other words have not been
assigned channel/format meanings without tracing their consumer. This byte is
not Nano's Nike setting. Video's initializer `0x1AF608` is a no-op; do not import
Nano Nike meanings into the unresolved eleven bytes at `0xB55..0xB5F`.

Previously proved Repeat, Shuffle, Sound Check and Clicker remain unchanged.
Video Clicker low bits are `0` Off, `1` Headphones, `2` Speaker and `3` On/both,
unlike Mini. Increment cycles only On/Off; named route branches do not establish
universal hardware exposure. The inherited contrast word at `0xAEC`, sleep word
at `0xAF4`, font selector at `0xB02`, and old timezone word at `0xB10` retain
partial status; inherited Settings code is insufficient to claim current UI use.

## Main Menu, EQ and language dependencies

Main Menu is u32 `0xB2C`. Native probes toggle every non-reset entry in the current
menu from an alternating-bit initial word and compare all saved bytes.

| Mask | Entry | Mask | Entry |
| --- | --- | --- | --- |
| `00000001` | Music | `00008000` | Playlists |
| `00000002` | Artists | `00000004` | Albums |
| `00200000` | Compilations | `00000008` | Songs |
| `01000000` | Podcasts | `00040000` | Audiobooks |
| `00000010` | Genres | `00000020` | Composers |
| `02000000` | Radio | `10000000` | Search, hardware-dependent |
| `00100000` | Photos | `00010000` | Photo Import |
| `04000000` | Videos | `00000200` | Extras |
| `00000040` | Clock | `00400000` | Stopwatch |
| `00800000` | Screen Lock | `00000080` | Contacts |
| `00000100` | Calendar / Calendars alias | `00000400` | Notes |
| `00020000` | Voice Memos | `00000800` | Games |
| `00080000` | Shuffle Songs | `00001000` | Backlight |
| `00002000` | Sleep | `08000000` | Hidden property `0x5F8C`, label unresolved |

Mask lookup `0x105A04` calls `0x130B30` for Search. Hardware words with upper
16 bits `0xB` and lower 16 bits below `0x11` return no Search mask. Other tested
hardware words return `0x10000000`. Residual mask bits remain unknown; the table
does not make the complete word resolved.

EQ remains byte `0x8E0` plus a u16 UTF-16 code-unit count at `0x8EA` and a
510-byte name allocation at `0x8EC`. The full serializer copies counts 0, 8, 13
and 255 exactly in the bounded probe, preserving the unused tail. Raw copy
behavior does not qualify overlong counts. Active Track EQ and global mode
determine which name is saved; see the [Video EQ evidence][eq].

The English bank's 22 names are Acoustic, Bass Booster, Bass Reducer, Classical,
Dance, Deep, Electronic, Flat, Hip Hop, Jazz, Latin, Loudness, Lounge, Piano, Pop,
R & B, Rock, Small Speakers, Spoken Word, Treble Booster, Treble Reducer and Vocal
Booster; an empty name represents Off. They are exact resource-localized keys,
not Classic numeric IDs. Startup clears an unrecognized name's count. The new
inventory retains the English choices; every other language's exact names and
a coordinated language/EQ editing workflow remain work to do.

Language is full **u32 `0xAF8`**, with codes
`0,1,3,4,5,8,9,10,11,13,14,15,16,17,18,19,20,21,22,23,24`. The prior native
qualification and new exact resource catalog retain all labels. English is
Video string `0x6063`, not an assumed shared Nano resource base. A one-byte
projection or an English name substituted in another language is insufficient.

## Photo, Video and Radio compound settings

Photo settings commit together through `0x192FF8`: UI bytes `+0x58/+0x59/+0x5E`
become file `0xB39/0xB3A/0xB3B`; UI `+0x5A/+0x5B/+0x5C/+0x5D` become
`0xB3C/0xB3D/0xB3E/0xB3F`; the u64 at UI `+0x60` becomes `0xB40`; UI
`+0x68` becomes `0xB49`. A setting cannot safely be understood from its isolated
setter while ignoring this retained compound state.

Native callback `0x16E33C` proves TV Out cycles `0→2→1→0`, TV Signal toggles
0/1, and Shuffle Photos / Repeat toggle 0/1. With TV capability disabled, the TV
action consumes the event without changing any Preferences bytes. Current Photo
and Video menus both contain TV Out/TV Signal. The candidate numeric labels
Off/On/Ask and NTSC/PAL still need a final direct label-getter trace; the inventory
keeps this distinction explicit.

Transitions use mode byte `0xB3B`: 0 Off, 1 Random, 2 Specific, with ID at
`0xB49`. `0x16EB88` sets Off/Random with ID `FF`; `0x16E9C4` returns the selected
property and resets an invalid specific ID to Off/FF. Current menu `0x502A` and
that getter identify IDs 1 Wipe across, 2 Wipe down, 3 Wipe from center, 6 Push
across, 8 Push down, 9 Cube across, 10 Cube down, 11 Page flip, 12 Radial,
13 Swirl and 14 Dissolve. ID 7 is recognized by the getter but its current label
is not established. The branch treats other nonzero modes except 1 as specific;
that is not an additional offered mode.

Time Per Slide byte `0xB3E` has visible ordered choices Manual, 2, 3, 5, 10 and
20 seconds in menu `0x5029`; the Video converter still needs qualification before
calling every numeric choice complete. Music byte `0xB3F` has native consumer
branches 0..4. Mode 2 uses Playlist persistent ID `0xB40`; absent mode-0/2 sources
fall back to mode 1. Mode 3 also uses a runtime index. Exact dynamic labels and
selection lifecycle need further work in `0x16D8B8/0x16E668`.

Radio-region byte `0xB4E` has a region-dependent default helper `0x9BCD0` and a
signed getter `0x9E894`. Strings `0x581F..0x5823` say Americas, Asia, Australia,
Europe and Japan. Their apparent ordinal order is not yet a qualified complete
band/spacing contract; trace Radio's property `0x581E` and consumers next.

## Clock storage, current timezone and the alarm projection

Current device zone components are signed u16 interpretations at `0xB62/0xB64`
and a DST byte at `0xB66`. Startup `0x1930C4` adds `0x62C8` and `0x61FB` to
the saved components, then calls resource-table lookups `0x237F20/0x237A9C`.
Save/apply `0x192CE8` performs the inverse through `0x238018/0x237BB8`, stores
both components via `0xB3E9C` and DST via `0xB3E70`, obtains a base offset and
applies it through `0xEC914`. Nonzero manual DST contributes 60 minutes. Defaults
are −1/−1/0; invalid pairs have a fallback involving resource IDs `0x62CD/0x6267`.
The complete valid pair table is still unenumerated. These fields are not an
epoch, raw RTC basis, IANA zone name or the Mini numeric timezone selector.

### Separate persistent Clock collection

Original literals at ROM `0x2AA84A` and `0x2AA844` construct
**`iPod_Control/Device/clock`**. Loader/saver `0x238F2C` opens that path and
reads/writes a root container 0 containing city-clock containers 1. Startup
`0x2381F8` calls that reader; when no clocks were loaded it creates a default city
record through `0x237CDC/0x142238`. Save wrapper `0xBC720` flushes this collection
when its own dirty byte is set. [Startup and path export][clock-record-export]

The native record serializer `0x142068` and nested alarm serializer `0x21E5A4`
establish the following **tagged values, not fixed whole-file offsets**:

| Container | Tag | Payload | Meaning |
| --- | ---: | --- | --- |
| City clock 1 | 2 | LE u32 | Region resource ID minus `0x62C8` |
| City clock 1 | 3 | LE u32 | City resource ID minus `0x61FB`, interpreted in region |
| City clock 1 | 20 / `0x14` | One byte | This city's manual DST flag |
| City clock 1 | 5 | Nested container | This city's alarm |
| Alarm 5 | 6 | LE u32 | Alarm minutes, in that city's civil clock basis |
| Alarm 5 | 7 | LE u32 | Alarm kind; 8 disabled, 4 Playlist; remaining sound choices incomplete |
| Alarm 5 | 31 / `0x1F` | LE u32 | Separate retained alarm word; meaning unresolved |
| Alarm 5 | 8 | LE u32 | Selection word used by Playlist path; full identity/lifecycle contract unresolved |

Container opening/closing words are LE `0x40000000 | tag` and
`0xC0000000 | tag`. A scalar record is LE tag, LE byte length, payload, then LE
`0x80000000 | tag`. There is **no alignment filler after the one-byte DST payload**
in the native emitted record. Two different 125-byte clock records roundtrip
through original byte framing and record logic for every input. The exact wire
hex is retained in the final receipt. This is record-level proof with synthetic
stream I/O, not a complete filesystem/invalid-stream acceptance matrix.

Original constructor `0x142238→0x21E714` initializes a new clock alarm to minute
**0**, kind **8**, and zero remaining words. Native cases supply Preferences
`0xB22=A2F2` or `F000` first: neither value enters the new clock. Reading a
sidecar record then installs minutes 480 or 1439 and the supplied alarm words,
while the **entire Preferences payload remains unchanged**. Thus persistent city
alarm values come from the separate sidecar, not an implied B22 import.

### Projection into Preferences and actual scheduling

Collection recomputation `0x238BF4` calls `0x237C5C` to choose the earliest
enabled alarm. It passes that result to `0x1935EC`, or creates a disabled-kind-8
fallback when none exists. The save callback converts the chosen occurrence to
minutes in the current device clock basis, writes low 12 bits of file `0xB22`,
preserves its high four bits, updates kind bits `0x0C` in `0xB18`, and copies a
Playlist persistent ID to `0xB24` when kind 4 applies. Add/change/delete, DST and
alarm-selection routes call this recomputation. [Collection export][clock-export],
[prior minute conversion and scheduling proof][calendar]

The reverse consumer also exists: Settings refresh notices B22/B18 changes and
emits property notifications; Clock handler `0x238D58` handles `0x60A1/0x60A3`
and invokes `0x2382E8`. That scheduler queries Settings property `0x60A2` for
minutes, constructs the pending calendar, and calls `0xB1F30` with selector 1.
Accordingly, changing the projection may affect pending scheduling; it still
does **not** edit a saved per-city alarm record, and later collection
recomputation can replace it.

The enable query needs a crucial qualification. Settings getter `0x190B00`
dispatches property **`0x60A3` to `0x191888`**, which calls the Clock singleton
and **`0x238D1C`**. That function returns the **current selected city record's
u32 kind at record `+0x14`**, not the cached Preferences flags. The property
masks `0x0C`: masked values 0, 4 and 12 produce resource `0x602E` (On), while
8 produces `0x602F` (Off), irrespective of other bits. With an empty collection,
the kind getter returns 0 and the property still returns On; this property alone
cannot establish that an enabled alarm exists. The scheduling function's enable
query therefore combines selected-city state with the saved minute projection.

By contrast, raw getter **`0x9B01C`** reads a u16 at owner `+0xB20`, hence file
`+0xB18`. Settings retains it at UI `+0x46`. Property **`0x60A4`**, branch
`0x1918D0`, actually reads that cached u16, masks `0x0C` and suppresses its
output when the result is 8. These are different observations. Furthermore,
earliest-alarm collection selector **`0x237C5C`** excludes the **full u32 kind
equal to 8**, not every kind whose masked low bits equal 8. Thus malformed
sidecar kind `0xFFF8` and canonical disabled kind 8 must not silently be equated
in a complete collection model. [Exact getter and selector export][enable-export]

A separate [supplementary receipt][enable-receipt] contains **27 native cases**:
nine independently executed on each input. The actual selected-city kind getter
and Settings dispatcher run with only collection element lookup, singleton and
initialization services adapted. Inputs 0/4/8/12 and FFF0/FFF4/FFF8/FFFC verify
the property mapping while Preferences B18 remains 0x28, and an empty-collection
case verifies the On fallback. Every original instruction is checked against its
source image and every Preferences byte is preserved. These cases supplement,
and do not change, the primary 393-case receipt or final-v5 field inventory.

This strengthens and narrows the previous B22 result. The previous native
minute-word proof remains valid. What was missing was ownership and persistence:
the current World Clock collection produces that word and persists elsewhere.
Application support should label it **Clock alarm snapshot**, explain that the
read-only saved time may be disabled or out of date, retain the observation,
and withhold the user-facing Video alarm editor until the `clock` contract is
qualified. A default B18 of 0x28 and B22 of zero must not imply an upcoming
midnight alarm. Do not derive actual collection enable state from the selected
city's property getter. The low-level byte-preserving codec remains useful
without claiming that it authors the selected persistent alarm. Calendar writing
is independent.

## Questions still open for each latest input

| Target | Firm conclusions | Remaining work |
| --- | --- | --- |
| Video 5 / updater 13 | Exact latest file and native cases; labelled scalar settings; current alarm projection and independent Clock record storage | All unresolved intervals; complete city pairs, sound/selection words and Clock file lifecycle; hardware identity for menu gates; USB adoption; volume-limit locking; Photo music/Radio domains; other-language EQ names |
| Video 5 / updater 20 | Independently checked identical OSOS and all 131 new cases | Same semantic questions; do not treat shared code as physical acceptance on every capacity/hardware configuration |
| Video 5.5 / updater 25 | Distinct full image checked, common code prefix and all 131 cases | Same semantic questions, plus concrete hardware mapping of Search and brightness branches; trailing image bytes do not answer those branches |

Highest-value next traces are Clock full-file parser/error recovery and selection
word `0x1F/8` consumers; complete city resource enumeration; pending alarm
notification/reload behavior; volume-lock provider `0x193498`; Photo dynamic
music `0x16D8B8/0x16E668`; Radio class property `0x581E`; and pointer-derived
consumers of the large leading unknown regions. Date/time ambiguity, malformed
values, unsupported preferences and unresolved fields must remain non-blocking
for Library loading, Calendar editing and Sync. Preserve their original bytes.

[receipt]: ../../../ipod-firmware-lab/artifacts/preferences-video-inventory-20261107-final-v2/receipt.json
[inventory]: ../../../ipod-firmware-lab/artifacts/preferences-video-fields-20261107-final-v5/field-inventory.json
[probe]: ../../../ipod-firmware-lab/scripts/research_video_preferences_inventory.py
[eq]: ../../../ipod-firmware-lab/notes/eq-video.md
[clock-record-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-clock-record-export-20261107-v1/index.tsv
[clock-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-clock-export-20261107-v1/index.tsv
[calendar]: ../../../ipod-firmware-lab/notes/video-calendar-alarm-2026-11-06.md
[enable-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-enable-review-export-20261107-v1/index.tsv
[enable-receipt]: ../../../ipod-firmware-lab/artifacts/preferences-video-enable-review-20261107-final-v2/receipt.json
