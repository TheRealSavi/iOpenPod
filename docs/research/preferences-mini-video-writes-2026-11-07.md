# Mini 2 and Video Preferences: qualified saved settings

Research date: 2026-11-07. This note covers Mini 2 updater family 7 / RetailOS
1.4.1 and Video updater families 13, 20 and 25 / RetailOS 1.3. It separates
the saved-file contract, original firmware execution with mocked services, and
live adoption on physical hardware. No physical device was accessed or changed
for this investigation.

The original menu callbacks and serializers support narrow, byte-preserving
edits to Shuffle, Repeat, Sound Check and Clicker. **Clicker labels differ between
Mini and Video:** raw low bits `1` mean Speaker on Mini but Headphones in Video's
combined menu. Native language writes are 32-bit, not a one-byte field. Backlight,
contrast and legacy EQ still need additional qualification before broader editing.
Most importantly, a running Preferences owner can overwrite a Host edit with its
retained RAM copy; a successful file write does not prove live adoption.

## Primary inputs and reproducibility

| Target | Exact input | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Mini 2, family 7, 1.4.1 | `Mini2FW/firmware/osos.bin` | 3,402,816 | `346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d` |
| Video family 13, 1.3 | `Video13FW/firmware/osos.bin` | 7,559,680 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| Video family 20, 1.3 | `Video20FW/firmware/osos.bin` | 7,559,680 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| Video family 25, 1.3 | `Video25FW/firmware/osos.bin` | 7,561,216 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` |

The Video 25 image contains the common Video 13/20 bytes followed by 1,536 zero
bytes. Each input is nevertheless independently loaded, hashed and probed; this
does not eliminate hardware-dependent branches. Provenance and runtime-map
construction are recorded in the lab's [Mini workspace](../../../ipod-firmware-lab/notes/mini2-firmware-workspace.md),
[Mini startup map](../../../ipod-firmware-lab/notes/mini2-startup-map.md) and
[independent Video verification](../../../ipod-firmware-lab/notes/games/video-family-independent-verification.md).

The final [probe script](../../../ipod-firmware-lab/scripts/check_mini_video_preferences.py)
uses Unicorn 2.1.4 and Capstone 5.0.7. Run from the lab with a new output directory:

```powershell
uv run scripts/check_mini_video_preferences.py --output artifacts/mini-video-preferences-NEW
```

The preserved [v3 receipt](../../../ipod-firmware-lab/artifacts/mini-video-preferences-20261107-v3/receipt.json)
contains **184 native cases**: 40 for Mini and 48 for each Video input. It includes
507 Mini and 963 per-Video executed instruction spans, each with address, length
and SHA-256. The script hash is
`2ea9341e69bc2f42f826b36327b2ebab7de1672e65640838e64e3ee96d22aac4`;
the `sidb_video_native.py` helper hash is
`c29b132765d4897fbe88d6ebb80de882f7b5fe465ed9832c1cbc0ca009d22395`.
The receipt itself hashes to
`21893214e2f25b6be72dbcd0352dca5947a7a9252fbb56a4db55a9771d088597`.

Original defaults, menu branches, field setters/getters, dirty serializers and
current-version loaders execute. Filesystem operations, allocation, notifications,
hardware queries and an unrelated Video playback-manager lookup are mocked and
listed in the receipt. Video startup relocation uses the existing guarded native
helper; Mini initialized blocks come from its hash-qualified corpus. The fixture
keeps live player volume/EQ state consistent with the owner before serialization.
It therefore proves the documented field behavior, not every possible live-player
overlay, USB state, audible output or physical persistence result.

## Framing and field bases

All file offsets below are relative to byte zero of
`iPod_Control/Device/Preferences`. The owner object's serialized payload begins at
**owner + 8**. A reference to owner `+0xB04`, for example, means file `+0xAFC`.

| Contract | Mini 2 / 1.4.1 | Video 13, 20, 25 / 1.3 |
| --- | --- | --- |
| Whole current file | `0xB3C` / 2,876 bytes | `0xB6C` / 2,924 bytes |
| Version, little-endian u32 at file `0` | `0x16` / 22 | `0x39` / 57 |
| Reset input, little-endian u32 at file `4` | Nonzero resets defaults | Nonzero resets defaults |
| Defaults | `0x00088C18` | `0x000F3DC0` |
| File reader | `0x000B1774` | `0x000E1B64` |
| Load/migrate | `0x000AF0DC` | `0x000AF698` |
| Owner constructor | `0x00088CE8` | `0x000A25B4` |
| Dirty full-file save entry | `0x000DD9A0` | `0x000BBF1C` |
| Dirty flag in owner, outside payload | `+0xB44` | `+0xB74` |
| Settings property callback | `0x000C5230` | `0x001919D8` |

Readers zero the buffer and read at most the current extent; loaders may migrate
older versions and reset invalid inputs. That firmware tolerance does not qualify
Host writing of truncated, extended or historical files. The Host writer requires
the exact studied framing and zero reset word. The inspected reader/loader and
serializer/write paths contain no Preferences checksum calculation or validation;
this is a bounded path finding, not a whole-firmware absence claim. Primary paths:
[Mini loader](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000af0dc.c),
[Mini save](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000dd9a0.c),
[Video loader](../../../ipod-firmware-lab/artifacts/preferences-video-20261107-export-v1/000af698.c)
and [Video save](../../../ipod-firmware-lab/artifacts/preferences-video-20261107-export-v1/000bbf1c.c).
The adjacent `.asm.txt` exports and final receipt provide instruction evidence;
decompiler prototypes alone are not treated as calling-convention proof.

## Verified saved setting representations

| Setting | File representation | Qualified meaning and edit rule |
| --- | --- | --- |
| Repeat | LE u32 `0x14` | `0` Off, `2` One, `1` All on all four inputs. UI order is Off/One/All, not raw ordinal order. |
| Shuffle | u8 `0x18` and u8 `0x8A` | Canonical Off `0/0`, Songs `1/0`, Albums `1/1`. Treat as a coupled field. Native Off can leave an irrelevant album flag unchanged when already disabled. |
| Sound Check | u8 `0xB16` | `0` Off, `1` On. Native callback, getter and full save verified. |
| Clicker, Mini | LE u32 `0xAFC`, low two bits | `0` Off, `1` Speaker, `2` Headphones, `3` Both. Preserve all upper bits. |
| Clicker, Video | LE u32 `0xAFC`, low two bits | Combined menu: `0` Off, `1` Headphones, `2` Speaker, `3` On/both. Preserve all upper bits. |
| Language | LE u32 `0xAF8` | Sparse language codes listed below; actual native setter width is four bytes. Preserve unrecognized words. |

Each native setting case passes the original UI property value, executes its
getter and serializes the complete file. The ordinary setting cases compare every
saved byte against the initial payload, allowing changes only in the indicated
field offsets. Clicker additionally starts with `0xA5A50000` and proves the upper
30 bits survive both the individual Video-switch paths and the resource-labelled
combined menus. See the [v3 cases and instruction hashes](../../../ipod-firmware-lab/artifacts/mini-video-preferences-20261107-v3/receipt.json).

The field accessors are useful independent anchors:

| Field | Mini getter / setter | Video getter / setter |
| --- | --- | --- |
| Shuffle | `0x00072B8C` / `0x000C66CC` | `0x0009EDB0` / `0x000B3A04` |
| Repeat | `0x00072184` / `0x000C63FC` | `0x0009E96C` / `0x000B3908` |
| Sound Check | `0x00072F44` / `0x000C6978` | `0x0009EF38` / `0x000B3D88` |
| Clicker | `0x00066F18` / `0x000C2788` | `0x0009B224` / `0x000B2E1C` |
| Language | `0x0006D004` / `0x000C4240` | `0x0009D758` / `0x000B3470` |

### Resource labels and the Clicker difference

The Mini English string directory is at ROM `0x001928A4`, with 474 twelve-byte
records and string data base `0x001951FC`. Video's directory is `0x00333308`, with
991 records and data base `0x003385F4`. Records contain LE u32 identifier, relative
offset and byte length. The probe retains each record's original bytes, address
and decoded UTF-8 text in [Mini resources](../../../ipod-firmware-lab/artifacts/mini-video-preferences-20261107-v3/7-english-resources.json)
and separately generated Video [13](../../../ipod-firmware-lab/artifacts/mini-video-preferences-20261107-v3/13-english-resources.json),
[20](../../../ipod-firmware-lab/artifacts/mini-video-preferences-20261107-v3/20-english-resources.json)
and [25](../../../ipod-firmware-lab/artifacts/mini-video-preferences-20261107-v3/25-english-resources.json)
resources.

Mini Repeat choices `0x27BA/0x27BB/0x27BC` and Video choices
`0x605C/0x605D/0x605E` explicitly say Off/One/All. Their menu callbacks use
indices `0/1/2`, but the setters store `0/2/1`. This resolves the otherwise
misleading numeric order.

Mini Clicker property `0x27E0` consumes English choices `0x27E1` Speaker,
`0x27E2` Headphones, `0x27E3` Both and `0x27E4` Off, storing low bits
`1/2/3/0`. Video property `0x6088` consumes `0x6089` On, `0x608A` Off,
`0x608B` Speaker and `0x608C` Headphones, storing `3/0/2/1`. The final native
probes execute these exact labelled choices for each image. Video's increment
branch cycles only On/Off; the named Speaker/Headphones branches still exist and
execute when supplied their choice IDs. This proves stored menu semantics, not
that every hardware profile exposes all four choices, nor the electrical routing
of audible clicks. It supersedes any inference that Mini bit labels can be reused
for Video merely because the file offset matches.

### Language width and sparse choices

The Mini English menu provides codes `0,1,3,4,5,8,9,10,11,13,14,16,17,18`.
Video additionally provides `15,19,20,21,22,23,24`. Their corresponding labels are:

| Code | Label | Scope |
| ---: | --- | --- |
| 0 | English | Both |
| 1 | Dansk | Both |
| 3 | Deutsch | Both |
| 4 | Español | Both |
| 5 | Suomi | Both |
| 8 | Français | Both |
| 9 | Italiano | Both |
| 10 | 日本語 | Both |
| 11 | 한글 | Both |
| 13 | Nederlands | Both |
| 14 | Norsk | Both |
| 15 | Português | Video |
| 16 | Svenska | Both |
| 17 | 简体中文 | Both |
| 18 | 繁體中文 | Both |
| 19 | Čeština | Video |
| 20 | Ελληνικά | Video |
| 21 | Magyar | Video |
| 22 | Polski | Video |
| 23 | Русский | Video |
| 24 | Türkçe | Video |

Every listed choice is included in the native receipt. This is a qualified raw
language representation, not proof of a complete Host language-switch workflow:
localized EQ names and other resource-dependent settings need separate review.
An unrelated edit must preserve the entire language word and all such dependent
data. The older generic one-byte projection must not be mistaken for the native
write width.

## Investigated fields that remain restricted

| Field | Evidence | Remaining boundary |
| --- | --- | --- |
| Backlight selector | LE u32 file `0xAF0`; Mini getter/setter `0x66FA0/0xC2A64`, Video `0x9B240/0xB2E74`. Native callbacks save injected Mini selectors `0..5` and Video `0..6`, changing no other saved bytes in the fixture. | These are selectors, not seconds. Complete visible menu/resource mapping and runtime timer behavior are not yet jointly qualified. Keep read-only. |
| Contrast | Mini LE u32 file `0xAEC`, getter/setter `0x68A30/0xC3494`, default `63`. Video retains the corresponding field and accessor pair `0x9B8B4/0xB2F18`. | Slider limits and display-hardware effects are unqualified. Do not assume Video uses a Mini contrast control. |
| Video brightness | u8 file `0xB54`, getter/setter `0x9B314/0xB2E90`; UI initialization installs `0..100` bounds. | Not included in the new complete native menu/save cases; hardware-specific initialization and application still need a bounded probe. |
| Video volume limit | LE u32 file `0xB50`, getter/setter `0xA035C/0xB408C`; default `100` in the studied fixture. | Do not reuse a historical one-byte `0..64` assumption. The complete UI domain and enforcement path remain unqualified here. |
| Legacy EQ | Enable u8 `0x8E0`; UTF-16 name count u16 `0x8EA`; name begins `0x8EC`. | Localized names, enabled state, active Track EQ and global selection interact. Do not substitute Classic's numeric preset word. |

Backlight English strings include Off, Always On and duration labels. In the
inspected Mini View records, choices `0x27A4/0x27A6/0x27A7/0x27A8/0x27A9`
bind Off/2/5/10/20 seconds; the absent `0x27A5` mapping is not filled in merely
from a nearby Always On string. Video includes an additional 15-second string,
but string presence alone is not a selector contract. The saved-word findings
come from the native receipt and the [Video menu export](../../../ipod-firmware-lab/artifacts/preferences-video-menu-20261107-export-v1/001919d8.c).

The established [Mini EQ](../../../ipod-firmware-lab/notes/eq-mini2.md) and
[Video EQ](../../../ipod-firmware-lab/notes/eq-video.md) notes provide deeper native
EQ evidence. Serializers copy the whole retained payload, overlay live volume
words at file `8/12` and live EQ-enable state, and conditionally copy the active
EQ name when the player's global-mode flag is set. Thus a Host file patch is not
equivalent to an in-firmware setter with all live objects updated.

Those earlier native registry probes establish 22 resource-localized built-ins
plus an empty Off entry, not a numeric enum in Preferences. A complete writer
still needs the active language resource-to-name mapping and a qualified bound
for the counted name buffer. The Mini startup probe demonstrates exact lookup:
an unknown saved name clears its count in RAM. Writing an English label for an
arbitrary saved language would therefore be an unsafe assumption. An English-only
writer could be qualified separately, but is not implied by the general field
map. The enable byte alone also does not prove the effective Track EQ behavior.

Clock and Alarm bytes are outside this writer scope. In particular, Mini file
`0xB10` is its saved timezone selector; Video file `0xB22` is an Alarm word, not
a timezone. See the [Mini/Video datetime investigation](mini-video-datetime-firmware-2026-11-06.md).

## Retained memory, refresh and adoption

The native fixture demonstrates both directions for each input:

1. Save the current owner, then externally patch language, Sound Check and an
   unrelated retained byte in the mocked file. The owner's next dirty save
   restores its old file exactly, losing the external edit.
2. Put the edited file back and execute the original loader. The owner receives
   the complete edited payload, including the unrelated byte. Its next full save
   preserves that payload exactly under the fixture's matched player state.
3. Set either the version word to zero or the second header word to one in that
   edited file. The original loader restores the complete defaults payload, and
   its next full save reproduces those defaults exactly. Both invalid-header
   cases execute independently on all four inputs.

These are original firmware executions with a mocked file adapter. They prove
the overwrite risk and a usable load path; they do not prove when that path is
called during a real USB detach. See the lifecycle cases in the
[final receipt](../../../ipod-firmware-lab/artifacts/mini-video-preferences-20261107-v3/receipt.json).

The bounded direct-call chain is Mini reader `0xB1774` → caller `0xAF0DC` →
owner constructor `0x88CE8` → application constructor `0xEB19C`; Video reader
`0xE1B64` → caller `0xAF698` → owner constructor `0xA25B4` → application
constructor `0x1D9430`. These are caller relationships, not the direction of
execution. Inspected Mini database rebuild `0xCC988` saves Preferences through
`0xDDD7C` before rebuilding Library objects; it does not invoke the Preferences
loader in its body. Video aggregate flush `0xBC094` also saves the retained owner.
The [Mini lifecycle export](../../../ipod-firmware-lab/artifacts/preferences-mini-lifecycle-20261107-export-v1/index.tsv)
and [Video menu/lifecycle export](../../../ipod-firmware-lab/artifacts/preferences-video-menu-20261107-export-v1/index.tsv)
retain the bodies and direct references. This does not exclude indirect reload
paths elsewhere, and the database refresh path is not relabelled as USB eject.

The application can truthfully report **saved to the Preferences file**. It cannot
yet promise immediately applied, retained after eject, or guaranteed adopted by
a specific reset sequence. A restart followed by verification is an appropriate
acceptance experiment, but a dirty flush before that restart can already have
overwritten the edit. Entering Disk Mode before editing may isolate the retained
RetailOS owner; the exact workflow and persistence still require separate
qualification. No such physical test was performed here.

## Application qualification and remaining work

[Device Registry's resolver](../../src/device_registry/preferences.py) returns a
typed `PreferencesSupport` with `MINI_2_1_4_1` or `VIDEO_1_3` only for a studied
model and exact retail release. Strongest-authority conflicting evidence is not
guessed away; observed updater families must agree. Transport revisions do not
substitute for firmware versions. The support result identifies a possible
format; exact framing, field permissions and masked/coupled edits belong to
iPodDB, while Storage owns publication. This separates identity evidence from a
file-size guess. The [Registry tests](../../tests/device_registry/test_preferences_support.py)
cover the seven latest target profiles, both Video 5th-generation updater families,
authority conflicts, missing evidence and historical-release rejection.

| Target | Qualified by this investigation | Remaining questions |
| --- | --- | --- |
| Mini 2 / 7 / 1.4.1 | Exact extent/version; native defaults/load/save; labelled Repeat/Clicker; Shuffle and Sound Check; sparse 32-bit language stores; retained-owner overwrite | Actual USB/eject reconstruction; safe physical adoption sequence; contrast limits; complete Backlight contract; localized global EQ authoring |
| Video / 13 / 1.3 | Independent source qualification and 48 native cases; same saved common fields, Video-specific Clicker mapping and language set | Hardware-conditional menu exposure; physical click routing; USB/adoption; brightness/volume-limit enforcement; Backlight and localized EQ authoring |
| Video / 20 / 1.3 | Independently loaded same full image and all 48 cases | Same runtime/hardware questions; binary equality does not resolve hardware branches |
| Video / 25 / 1.3 | Independent full-image hash and all 48 cases, with its trailing padding retained | Same runtime/hardware questions; appended padding does not establish hardware behavior |

Preferences research and optional Settings failures remain separate from Library
loading and Sync. Unknown clock values, unqualified setting fields and unfamiliar
saved bytes stay preserved; none should become a datetime-related Library blocker.
