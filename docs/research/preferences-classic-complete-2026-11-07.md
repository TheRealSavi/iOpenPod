# Latest Classic Preferences: complete inventory pass and explicit gaps

Investigated November 7, 2026. This report covers only Classic 6 / 1.1.2,
Classic 6.5 / 2.0.1, Classic 7 / 2.0.4 and Classic 7.5 / 2.0.5. The request's
“6.6” is interpreted as the already studied 120GB Classic 6.5. No older release
is used to qualify a current setting.

The common layout now has independently recovered menu catalogs, language
choices, Backlight display domains and more video-setting distinctions. The
Alternate Audio saved-setting route is native-tested on **all four** targets.
A complete semantic interpretation of every serialized byte has **not** been
achieved. The accompanying inventory partitions every byte and distinguishes
resolved fields, partial meanings and unbound intervals. None of the unbound
intervals is declared padding merely because defaults clear it.

This is firmware research and documentation, not an expansion of the application
write profile. There was no physical-device I/O, network firmware download,
publication or application-code change in this group.

## Exact targets and evidence

All file offsets below are relative to `iPod_Control/Device/Preferences`.
Multi-byte scalars are little-endian. The retained Preferences payload begins at
native context `+4`; the owner pointer is at `+0xce8` for 24/33 and `+0xf00` for
35/38. Runtime addresses are not file offsets.

| Target | Latest image SHA-256 | File extent | Native version |
| --- | --- | --- | --- |
| 24 / Classic 6 / 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` | `0xb88` / 2,952 | `0x3c` |
| 33 / Classic 6.5 / 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | `0xb8c` / 2,956 | `0x3d` |
| 35 / Classic 7 / 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | `0xb8c` / 2,956 | `0x3e` |
| 38 / Classic 7.5 / 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | `0xb90` / 2,960 | `0x3f` |

Three new receipts are the reproducible evidence for this pass:

- [Native catalogs][catalog]: original menu initializers, per-row mask functions,
  modern Backlight and legacy display-property branches; source resource banks
  supply labels. SHA-256
  `fb08d0156e62b616a152f603502800477bdf99330307fb727142054a4db1b3cf`.
- [Alternate Audio][alternate]: **1,024** original-instruction UI mutations,
  every initial byte `0..255` on each target, including dirty marking and exact
  unrelated-payload preservation. SHA-256
  `2343679a5f74c7de5a0a80d0398cb0bed1b2ced142b1c83134b8cb495af385ec`.
- [Byte inventory][inventory]: **860** native scalar-getter vectors across
  42/43/43/44 getters, plus twelve explicitly attributed prior-research fields
  per target. It contains 54/55/55/56 field entries and an exact gap-free byte
  partition. SHA-256
  `529de61089f996305134a82c10ca578d46025fc0a69cc28794aa67f2e01cbe9a`.

Each receipt pins original image and runtime-map identities and records source
script/helper hashes. Instruction windows and executed-address hashes are kept
separately: an allowlisted window is not claimed to be the exact recovered
function body. Native scalar probes also compare exported instruction bytes to
the original firmware before execution. Typed getters prove byte access and
sign extension, not the control's purpose or safe authoring domain.

The catalog probe executes native initializers and mask/display dispatch. Its
explicit stubs are resource/string ownership services, a controlled legacy UI
property query and the capability predicate used by Search. Alternate Audio
executes the native UI handler, native saved-byte setter and native dirty marker;
the media singleton and virtual application boundary are mocked. This does not
execute a movie decoder, complete observer graph, USB lifecycle or hardware.

The parent investigation supplied image adapters, relocation normalization and
resource-bank/block parsers. These are imported by name and hashed, rather than
silently copied. Parent leaf candidates and menu graphs were discovery clues.
The new [read-only Ghidra survey][survey] also selected owner-member references
and their callers; same-offset hits in other objects are not Preferences proof.
The manually located 24 Main initializer at `081bcaac` is disclosed in the receipt
and subsequently executes its own original instructions. No uniform address
shift is used to assert matching semantics.

## Menu preferences: shared bits and model-specific extensions

`+0xb2c` is Main Menu visibility; `+0xb80` is a separate Music Menu mask.
Targets 33/35/38 add Main Menu group 1 at `+0xb88`. These are u32 bitfields,
not arrays of menu indices. The native catalogs include row identity, localized
label identifier, legacy property, initial row flag, mask, group and file offset.
Initial row flags are not substituted for the saved/default mask provider.

| Property | 24 | 33 | 35 | 38 |
| --- | --- | --- | --- | --- |
| Main rows, including Reset | 32 | 33 | 34 | 34 |
| Music rows, including Reset | 12 | 13 | 13 | 13 |
| Main `b88` bit 0 | absent | Genius | Genius Mixes | Genius Mixes |
| Main `b88` bit 1 | absent | no offered row bound | iTunes U | iTunes U |
| Music `b80` bit 12 | no offered row bound | Genius | Genius Mixes | Genius Mixes |

Common Main mask bits are:

| Bit | Main row |
| --- | --- |
| 0, 1, 2, 3 | Music, Artists, Albums, Songs |
| 4, 5, 6, 7 | Genres, Composers, Clocks, Contacts |
| 8, 9, 10, 11 | Calendars, Extras, Notes, Games |
| 12, 13, 14 | Music Videos, Sleep, Alarms |
| 15 | **Both Playlists and Video Playlists** |
| 18, 19, 20, 21 | Audiobooks, Shuffle Songs, Photos, Compilations |
| 22, 23, 24, 25, 26 | Stopwatch, Screen Lock, Podcasts, Radio, Videos |
| 28 | Search, conditional on a capability predicate |
| 29, 30, 31 | Cover Flow, Movies, TV Shows |

Bits 16, 17 and 27 are not offered rows in these recovered Main tables.
The mask helper recognizes additional legacy IDs, but that does not establish
current controls for them. **Rentals produces mask zero** on all four; it must
not be assigned a fabricated independent visibility bit. Reset Menu is an
action, not a saved flag. Search's mask is zero when its predicate is false;
the corresponding physical capability is still to be fully identified.

The common Music mask is bit 0 Cover Flow, 1 Playlists, 2 Artists, 3 Albums,
4 Compilations, 5 Songs, 7 Radio, 8 Genres, 9 Composers, 10 Audiobooks and
11 Search; bit 12 is the later Genius/Genius Mixes extension. Bit 6 has no
recovered offered row. All other bits remain preserved. Unlike Main Search,
Music Search's recovered mask is not conditional in this helper.

Family 33's Main read/write routes `0814fbcc` / `0814fc8c` choose group 0 or 1
before testing/toggling a mask. Its modern UI toggles `081c8414` and `081c8660`
separately update Main and Music. Item visibility, notifications and menu refresh
also occur; an on-disk bit patch does not reproduce those live operations.

| Native function | 24 | 33 | 35 | 38 |
| --- | --- | --- | --- | --- |
| Main initializer | `081bcaac` | `081c73c4` | `081e15b8` | `081e23e0` |
| Music initializer | `081bd234` | `081c7b64` | `081e1d84` | `081e2bac` |
| Item-to-mask | `080ad1e0` | `080b0554` | `080c7320` | `080c73c4` |
| Item-to-group | absent | `080c050c` | `080d717c` | `080d7228` |
| Language selection | `081bc938` | `081c7250` | `081e1444` | `081e226c` |
| Legacy display provider | `081466b4` | `0814cf34` | `081649d4` | `08165198` |

## Language and Backlight domains

All four language tables contain the same sparse stored codes at `+0xaf8` u32:

| Saved code | Language | Saved code | Language |
| --- | --- | --- | --- |
| 0 | English | 1 | Danish |
| 3 | German | 4 | Spanish |
| 5 | Finnish | 8 | French |
| 9 | Italian | 10 | Japanese |
| 11 | Korean | 13 | Dutch |
| 14 | Norwegian | 15 | Portuguese |
| 16 | Swedish | 17 | Simplified Chinese |
| 18 | Traditional Chinese | 19 | Czech |
| 20 | Greek | 21 | Hungarian |
| 22 | Polish | 23 | Russian |
| 24 | Turkish | — | — |

The receipt preserves exact native display order, original-language labels,
resource-bank IDs and event IDs (`0x6067 + saved code`). Codes are not contiguous
menu indices. The callback uses its selected row to change the active resource
provider, sets legacy language property `0x6066`, and invokes reload/notification
services. This pass extracts the callback-referenced table; it does not emulate
those reload services. Unknown u32 codes remain exact, including nonzero upper
bytes. Language-dependent date formatting is not permission to rewrite clock
bias or infer an IANA timezone.

The timer selector `+0xaf0` u32 has this native display domain on every target:

| Saved selector | Display meaning | Offered in seven-row Settings list |
| --- | --- | --- |
| 0 | Off | yes |
| 1 | 2 Seconds | yes |
| 2 | 5 Seconds | yes |
| 3 | 10 Seconds | yes |
| 4 | 20 Seconds | yes |
| 5 | 30 Seconds | yes |
| 6 | Always On | yes |
| 8 | 15 Seconds | **no** |
| 7, 9 | No new string requested by the tested display path | no |

The native raw getter/setter accepts its full u32 representation. Legacy UI
property `0x6031` caches a byte and uses event `0x6032 + selector`; this is not a
seconds count. Unknown display paths can reuse string state; they are not proof
that a value is Off. The actual elapsed-timer consumer and handling of every
noncanonical word remain open. The 33 Backlight screen temporarily changes an
Off setting while entering its editor (`081d1814`), and has exit restoration
logic (`081d18a8`), so preview and committed state must be distinguished.

A **separate** signed-byte field at `+0xb4a`, legacy property `0x6004`, displays
0 Off, 6 Always On, 9 While Playing and 10 On Keypress. Its 33 callback cycles
`0 → 10 → 9 → 6 → 0`. All four display providers independently confirm these
labels; the corresponding source is titled Backlight. The activity policy's
interaction with the timer, playback and accessory modes is not yet traced.
The neighboring `+0xaec` u32 is not established as another timeout.

## Video controls and non-Boolean storage semantics

The English SORC resources independently bind these property titles on all four.
Native display probes then exercise values 0, 1, 2 and 255 through each image's
own property provider. The file-to-cache mutation/refresh chain for the new
controls is directly reviewed on 33; all-four native mutation proof is presently
limited to Alternate Audio. Other targets' file getters are independently
executed, but that is not a substitute for closing their entire mutation chain.

| File field | Property / 33 cache | Canonical display meaning | Important qualification |
| --- | --- | --- | --- |
| `b39` i8 | `60ef` / `60` | 0 Off, 1 On, 2 Ask: TV Out | Other nonzero sampled values display On; native UI cycles 0→2→1→0 and remaps live media modes. |
| `b3a` i8 | `60f0` / `61` | 0 NTSC, 1 PAL: TV Signal | Nonzero sampled values display PAL; regional defaults and actual signal generation remain partial. |
| `b4d` u8 | `60bd` / `86` | **0 On, 1 Off: Fit to Screen** | This control is inverted; nonzero sampled values display Off. |
| `b84` u8 | `60be` / `87` | 0 Standard, 1 Widescreen: TV Screen | Nonzero sampled values display Widescreen. |
| `b74` u8 | `60f1` / `8c` | 0 Off, 1 On: Captions | Native UI also calls the Subtitles live setter. |
| `b85` u8 | `60f2` / `8d` | 0 Off, 1 On: Alternate Audio | Every raw initial byte tested on all four; toggle is 0→1, all other bytes→0. |
| `b86` u8 | `60f3` / `8e` | 0 Off, 1 On: Subtitles | Native UI also calls the Captions live setter. |

Captions/Subtitles are not qualified as unrelated independent Boolean edits.
Their media observer callbacks may publish further saved changes; this pass
stubs that boundary and leaves the coupling unresolved. Fit to Screen's inverse
polarity is established by native display execution, not a guessed bit label.

Alternate Audio's all-four test verifies only the settings-service mutation,
retained byte, dirty flag and applied Boolean. The global switch is not a
language identifier. The [earlier movie trace][movie] found exact-language/first-
enabled-track selection but did not close the switch-to-requested-language
bridge. That remains open on all four, even though the saved-setting path is
now equally understood.

38 adds `+0xb8c` u8. Static review identifies EU Volume Limit: getter `0804b06c`,
setter `0805ce10`, action `0821e714`, maximum provider `081558c0`. The provider
returns internal 256 when both regional predicates are false; otherwise it
returns 222 for zero and 168 for nonzero. The action references
`GotoScreen_EUVolumeLimitConfirmation`. Enabling calls the live player to reapply
its current volume. This is **static instruction/decompiler evidence**, not a
new native execution qualification or acoustic calibration. The exact regional
predicates, confirmation semantics and interaction with `b50` remain partial.

## Full byte inventory and remaining questions

The JSON inventory uses integer `file_offset`, `size`, `end_exclusive`, exact
getter address/hash, raw representation/domain, native vectors and semantic
status. `partition` covers `[0, file_extent)` without gaps or overlap;
`resolved_intervals` and `unresolved_or_partial_intervals` explicitly separate
canonical meaning from retained uncertainty. Raw representability, UI-offered
values, callback normalization and actual runtime behavior are distinct domains.
A u8 representation permits all 256 byte patterns without making them 256
understood user choices.

Shared unbound spans in this consolidated inventory are:

```text
[010,014) [019,08a) [08b,091) [092,8e0) [8e1,aec)
[b00,b02) [b04,b0a) [b0e,b14) [b17,b18) [b1a,b1c)
[b21,b22) [b24,b2c) [b30,b38) [b4f,b50) [b55,b60)
[b63,b6c) [b6d,b70) [b75,b78) [b87,b88)
```

These coordinates are hexadecimal, end-exclusive. 38 additionally has
`[b8d,b90)`. Some spans have useful static hints: 33 runtime methods read/clear
`b00`, set `b17` and `b30`; the legacy EQ name migration consumes the region
starting at `8ea`; a default helper is passed `b55` but the 33 helper `0817f514`
is a return-only stub. These observations do not establish the enclosing spans
as settings, active structures or unused padding. The large leading regions
need context-argument and indirect-consumer tracing, not just more narrow
owner-pointer getter scans.

Typed but still partial fields include contact sort/display (`b0c`, `b14`),
format word `b18`, clock display flags `b1c`, `b20`, `b22`, audiobook speed
`b38`, slideshow candidates `b3b..b49`, regional radio byte `b4e`, volume limit
`b50`, `b62`, city/DST/bias fields and unused mask bits. The inventory deliberately
labels slideshow assignments as candidates where this pass did not bind native
UI titles and consumers. Contacts' resource requests are legacy numeric IDs
outside the recovered English string bank; missing label lookup is not a
resolved first-name/last-name ordering.

| Target | Questions specific to this target, in addition to shared gaps |
| --- | --- |
| 24 / 1.1.2 | Close the live effects of its shorter Main/Music tables and the shared Playlist bit; there is no serialized `b88` extension. Trace its own Alternate Audio movie bridge and activity-policy/timer precedence. |
| 33 / 2.0.1 | Resolve the remaining 31 `b88` bits beyond the known Genius bit, the role of Main Rentals' zero mask and the observed return-only `b55` initializer. This target has the fullest reviewed refresh/observer graph but its Captions/Subtitles persistence coupling is still open. |
| 35 / 2.0.4 | Trace Genius Mixes/iTunes U capability and refresh effects; identify every unoffered extension-mask bit. Close video-setting mutation/observer routes independently rather than importing 33's runtime object model. |
| 38 / 2.0.5 | All 35 questions plus EU Volume Limit predicates, confirmation callback, user limit interaction and trailing `[b8d,b90)` bytes. Its inserted Settings property shifts subsequent IDs; do not reuse 33 IDs blindly. |

Shared next entry points are the exact UI providers in the table above, their
per-field native getters in the inventory, the 33 refresh `081502e8`, legacy
mutation `0814df14` (24 `08147694`, 35 `081659bc`, 38 `08166180`) and the
read-only export reference tables. For clock/DST, retain the existing split
between raw clock, saved bias, city and DST rules; unknown timestamps never
block unrelated edits or device loading. No host datetime conversion is added
here, so the existing `whenever` boundary remains unchanged.

Finally, saved-file verification still does not prove live adoption. Current
firmware can reuse retained Preferences and overwrite a Host edit on a later
flush. USB disconnect/disk-mode exit/reboot ordering remains an all-four question.
The existing [qualified-write report][prior] documents exact-frame validation,
reset-word handling and whole-payload preservation; this report does not weaken
those requirements or expand authored values based on labels alone.

## Reproduction and checks

From `ipod-firmware-lab`, choose new output directories each time:

```powershell
uv run scripts/research_classic_preferences_full.py --output artifacts/NEW-classic-catalogs
uv run scripts/research_classic_alternate_audio.py --output artifacts/NEW-classic-alternate
uv run scripts/research_classic_preferences_byte_inventory.py --output artifacts/NEW-classic-inventory
```

PEP 723 pins Python 3.12, Capstone 5.0.7 and Unicorn 2.1.4. The inventory requires
read-only exports under `artifacts/preferences-classic{24,33,35,38}-full-export-20261107`.
These were produced with `PreferencesClassicFullInventory.java`, `-readOnly`
and `-noanalysis`, using the already prepared Ghidra projects. Supplementary 33
UI/backlight exports used the existing read-only `PreferencesNanoExport.java`
with new Classic-specific seed files. Original programs and firmware were not
changed. Exported decompilation names/types are analyst annotations.

All three final scripts were Ruff-formatted and checked before final receipts
were regenerated. No application behavior changed, so no application tests
were added. The native receipts validate the actual research claims; they are
not tests which merely restate a newly authored codec.

[catalog]: ../../../ipod-firmware-lab/artifacts/preferences-classic-native-catalogs-20261107-final/native-catalogs.json
[alternate]: ../../../ipod-firmware-lab/artifacts/preferences-classic-alternate-audio-20261107-final/alternate-audio.json
[inventory]: ../../../ipod-firmware-lab/artifacts/preferences-classic-byte-inventory-20261107-final/byte-inventory.json
[survey]: ../../../ipod-firmware-lab/scripts/ghidra/PreferencesClassicFullInventory.java
[movie]: ../../../ipod-firmware-lab/notes/itunesdb/video-alternate-audio.md
[prior]: preferences-classic-writes-2026-11-07.md
