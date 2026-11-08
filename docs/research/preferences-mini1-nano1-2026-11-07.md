# Mini 1 and Nano 1 Preferences: native saved-format qualification

Research date: 2026-11-07. This investigation qualifies the latest Mini 1 and
Nano 1 firmware independently of the earlier Mini 2 and Video work. It uses
original Apple firmware bytes and bounded offline execution; no physical iPod
was accessed, and no firmware or application files were installed on a device.
Nano 2 is outside this scope.

Mini 1 and Nano 1 support the same four narrow saved settings: Shuffle, Repeat,
Sound Check and masked Clicker. Both use Clicker low bits `1` for Speaker and
`2` for Headphones, unlike the studied Video combined menu. Mini 1 also independently
qualifies the 50-choice fixed-offset timezone observation used for Mini 2. Nano 1
does **not** acquire a timezone interpretation from its similar field offsets.

## Exact releases, inputs and qualification boundaries

The newly retained [Apple update catalog](../../../ipod-firmware-lab/artifacts/preferences-latest-catalog-20261107/apple-version-catalog.plist),
SHA-256 `5a2938b0aa28808cb738b0871e01d6e084c5f56243d69b0c6c4fabec442586b8`,
lists Mini updater families 3/6 at visible release 1.4.1 and Nano families 14/17
at 1.3.1. Package manifests retain their separate family identifiers. Internal
build versions are different identifiers and are not substituted for the visible
retail release. See the lab's [Mini identity comparison](../../../ipod-firmware-lab/notes/mini-updater-family-identities.md)
and [Nano 1 identity comparison](../../../ipod-firmware-lab/notes/nano1-updater-family-identities.md).

| Model and updater | RetailOS | OSOS bytes | OSOS SHA-256 | Proposed explicit profile |
| --- | --- | ---: | --- | --- |
| Mini 1 / 3 | 1.4.1 | 3,402,984 | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` | `MINI_1_1_4_1` |
| Mini 1 / 6 | 1.4.1 | 3,402,984 | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` | `MINI_1_1_4_1` |
| Nano 1 / 14 | 1.3.1 | 5,566,256 | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` | `NANO_1_1_3_1` |
| Nano 1 / 17 | 1.3.1 | 5,566,256 | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` | `NANO_1_1_3_1` |

Each updater's own extracted input is loaded and hashed by the new probe, even
though the two inputs within each model are byte-identical. Each also compares
against its shared workspace image. This establishes code/data equality for these
exact inputs, not identical hardware-dependent behavior or historical firmware
compatibility. The [Mini 1](../../../ipod-firmware-lab/notes/mini1-firmware-workspace.md)
and [Nano 1](../../../ipod-firmware-lab/notes/nano1-firmware-workspace.md) workspaces
retain their original packages and acquisition/extraction receipts.

## Reproducible native evidence

Run the [new verifier](../../../ipod-firmware-lab/scripts/check_mini1_nano1_preferences.py)
from the firmware lab with a new output directory:

```powershell
uv run scripts/check_mini1_nano1_preferences.py --output artifacts/mini1-nano1-preferences-NEW
```

The [final v2 receipt](../../../ipod-firmware-lab/artifacts/mini1-nano1-preferences-20261107-v2/receipt.json)
records **250 passing native cases**: 86 for each Mini input and 39 for each Nano
input. It contains 633 executed four-byte instruction spans per Mini and 543 per
Nano, each with address and SHA-256, plus input paths/hashes, mapped-block hashes,
resource records and mocked function addresses. Per-target instruction listings
and English resources are retained beside the receipt.

- Script SHA-256:
  `a967bcba1a076286030d6f4591c0a6bd3edfca217bba1236ed22a64019f1a3f1`.
- Receipt SHA-256:
  `c608f81e4e197f31a6833af9ff0757b50141a085e53d8a752bc922f8c15fe84c`.
- Register/file-adapter helper, `check_mini_video_preferences.py`:
  `2ea9341e69bc2f42f826b36327b2ebab7de1672e65640838e64e3ee96d22aac4`.
- Imported transitive helper, `sidb_video_native.py`:
  `c29b132765d4897fbe88d6ebb80de882f7b5fe465ed9832c1cbc0ca009d22395`.
- Runtime: Unicorn 2.1.4 and Capstone 5.0.7. Ruff formatting and lint passed.

The new Machine constructor independently loads each exact Mini/Nano image and
its verified initialized corpus blocks; it does not call the previous Mini 2 or
Video constructor. The [Mini 1 startup map](../../../ipod-firmware-lab/notes/mini1-startup-map.md)
and [Nano 1 startup map](../../../ipod-firmware-lab/notes/nano1-startup-map.md)
establish those blocks and BSS. The fixture supplies owner/player/UI objects and
executes original defaults, menu callbacks, getters, setters, readers, loaders and
full-file serializers. Allocation, filesystems, notifications, hardware queries
and an unrelated Nano playback-manager lookup are adapters. Mini timezone probes
stop at a captured clock-setter call. They do not execute raw RTC writes.

These are bounded function tests, not a complete boot, display-language provider,
playback, USB lifecycle or physical persistence test. Output directories refuse
overwriting, source hashes are asserted, and the original images remain unchanged.

## Saved file and lifecycle anchors

The file is `iPod_Control/Device/Preferences`. Every field offset in this note is
**file-relative**. Its payload begins at **owner + 8**; for example, owner `+0xB04`
is file `+0xAFC`.

| Contract or function | Mini 1 / 1.4.1 | Nano 1 / 1.3.1 |
| --- | --- | --- |
| Exact current payload | `0xB3C` / 2,876 bytes | `0xB64` / 2,916 bytes |
| LE u32 version at file `0` | `0x16` / 22 | `0x37` / 55 |
| Defaults | `0x000888E4` | `0x00065944` |
| Path builder | `0x00062B38` | `0x0004B008` |
| Reader | `0x000B1460` | `0x00056CE4` |
| Load/migrate | `0x000AEDC8` | `0x000317B0` |
| Owner constructor, static caller | `0x000889B4` | `0x000269C0` |
| Dirty full-file save | `0x000DD840` | `0x0003B604`, branching to `0x0003B4DC` |
| Dirty flag outside payload | Owner `+0xB44` | Owner `+0xB6C` |
| Settings property callback | `0x000C5098` | `0x000ED5D4` |

The Mini save path's literal at `0xDD834` points to the path string at ROM
`0x1652E4`; its extent literal at `0xDD838` is `0xB3C`. The Nano save body embeds
the same device-relative path and loads `0xB64` from `0x3B5FC`. Primary exported
paths are the [Mini writer](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000dd840.c),
[Mini reader](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000b1460.c),
[Nano writer](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/0003b604.c)
and [Nano reader](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/00056ce4.c).
Adjacent assembly exports and the native receipt bind these recovered descriptions
to actual instructions; the C-like output is not original Apple source.

Readers clear their destination and clamp their read length to the current
extent. Native oversized-file tests confirm the tail is not copied. An empty file,
a zero first version word, or a nonzero second u32 at file `4` causes the higher
loader to restore defaults in the tested cases. The complete resulting payload
matches native defaults. The current version with a zero second word preserves
the supplied payload in the tested loader path. Older versions have migration
branches; those are not qualified Host-writing profiles. See the
[Mini loader](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/000aedc8.c),
[Nano loader](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000317b0.c)
and the final receipt's header, empty-file and oversized-reader cases.

No checksum calculation or check occurs in the inspected Preferences read/load
and serialize/write paths. This is a bounded finding, not proof of whole-firmware
absence. Host editing should require exact current extent/version and zero reset
word; native tolerance of truncation, tails or historical formats is not permission
to rewrite them.

## Native fields, coupled edits and exact labels

| Setting | File representation | Confirmed domain and edit behavior |
| --- | --- | --- |
| Repeat | LE u32 `0x14` | `0` Off, `2` One, `1` All on both models |
| Shuffle | u8 `0x18` plus u8 `0x8A` | Canonical Off `0/0`, Songs `1/0`, Albums `1/1`; native early-return can preserve an irrelevant album flag when already Off |
| Sound Check | u8 `0xB16` | `0` Off, `1` On |
| Clicker | LE u32 `0xAFC`, low two bits | `0` Off, `1` Speaker, `2` Headphones, `3` Both; preserve upper 30 bits |
| Language | LE u32 `0xAF8` | Sparse native codes below; width is four bytes |

Each ordinary setting case executes the actual labelled UI callback, checks its
getter, serializes the complete file and compares every byte outside the intended
field or coupled fields. Clicker starts with upper bits `0xA5A50000` and confirms
their exact retention under every named choice. None of these probes merely
assumes that an ordinal equals its saved encoding.

| Field | Mini getter / setter | Nano getter / setter |
| --- | --- | --- |
| Shuffle | `0x72858` / `0xC6534` | `0x237FC` / `0x354DC` |
| Repeat | `0x71E50` / `0xC6264` | `0x233D8` / `0x35428` |
| Sound Check | `0x72C10` / `0xC67E0` | `0x23984` / `0x35860` |
| Clicker | `0x66BCC` / `0xC2488` | `0x204C8` / `0x34C10` |
| Language | `0x6CCB8` / `0xC40A8` | `0x22328` / `0x34FC8` |

Mini English resources use container base `0x19260C`, string directory
`0x192BEC` (474 records), and data base `0x195544`. Nano uses base `0x29797C`,
directory `0x2988E4` (1,134 records), and data base `0x29E158`. Records are LE
u32 ID, relative offset and byte length. The probe asserts header structure,
terminating NUL and UTF-8 decoding, and saves the exact records and addresses in
the independently produced [Mini 3](../../../ipod-firmware-lab/artifacts/mini1-nano1-preferences-20261107-v2/3-resources.json),
[Mini 6](../../../ipod-firmware-lab/artifacts/mini1-nano1-preferences-20261107-v2/6-resources.json),
[Nano 14](../../../ipod-firmware-lab/artifacts/mini1-nano1-preferences-20261107-v2/14-resources.json)
and [Nano 17](../../../ipod-firmware-lab/artifacts/mini1-nano1-preferences-20261107-v2/17-resources.json)
resource artifacts.

Mini Repeat choices `0x27BA..0x27BC` and Nano choices `0x605B..0x605D` label
Off/One/All. Their setters convert UI indices `0/1/2` to raw `0/2/1`.
Mini Clicker property `0x27E0` uses choices `0x27E1..0x27E4`; Nano property
`0x6087` uses `0x6088..0x608B`. Both resource sequences explicitly label
Speaker/Headphones/Both/Off, and native saves produce `1/2/3/0` respectively.
The studied Video firmware's reversed combined-menu mapping is therefore not
transferred to Nano by appearance or generation proximity. These are native menu
semantics, not an audible-output or physical routing test.

The native Mini language choices are `0,1,3,4,5,8,9,10,11,13,14,16,17,18`.
Nano additionally supplies `15,19,20,21,22,23,24`. Every available choice in these
sets is exercised, with its exact resource label retained in the receipt. A
language observation alone is not a complete language-changing workflow: resource
dependent values, such as localized EQ names, must be considered separately.
Unknown words and untouched high bytes remain preserved.

## Mini 1 timezone: qualified observation, not a clock writer

Mini 1 file `0xB10` is a **u32 saved menu selector**, with valid observed choices
`1..50`. Its own signed-byte table at ROM `0x1925B8` encodes adjacent standard/DST
pairs for base hours `-12..+12`. Effective offsets run from `-12` to `+13` hours.
Selection `s` uses index `s-1`, effective minutes `table[s-1] * 60`, and a manual
DST state given by index parity. These are fixed menu choices, not IANA identities
or historical timezone rules.

The native path `0xC5098` → setter `0xC6ADC` → application `0x32994` reads that
table and calls clock setter `0x836BC` with mask `0x180`. All 50 menu choices execute
and save exactly the selector word; the captured clock-setter record contains
the independently expected signed base minutes at record `+10` and DST minutes
`0/60` at `+12`. Getter `0x73A98` returns the selection. See
[menu application](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/00032994.asm.txt)
and the final receipt's `mini_timezone_selector` cases.

Resolver `0x73AA4` gives valid live-clock offset state priority; with that validity
provider stubbed false, native cases for saved values `0,1,16,50` confirm the
saved-value fallback. Zero produces a firmware default resource choice, but the
Host should retain zero as **unknown**, rather than inventing device timezone
evidence from a firmware UI default. Full live-clock arbitration, raw RTC effects
and UTC basis are outside this new bounded probe. The neighboring file `0xB18`
word is a distinct setting; it must not be confused with owner `+0xB18`, which
corresponds to file `0xB10`. [Resolver](../../../ipod-firmware-lab/Mini1FW/evidence/corpus/functions/00073aa4.c).

This supports using Mini 1's captured selection as the same kind of read-only
fixed-offset observation qualified for Mini 2. It does not authorize calendar
changes or timezone writes. Nano 1's timezone and Alarm interpretation remain
unqualified by this investigation, so its new model should expose the verified
language word without importing Video or Mini clock fields.

## Additional observed settings and open writer boundaries

The inspected Backlight setters store a selector in LE u32 file `0xAF0`:
Mini `0xC2764`, Nano `0x34CF0`. Their complete menu/timer domain has not been
qualified here, so the field stays read-only. Contrast-like file `0xAEC` has
scalar setters, including Nano `0x34D78`, but the slider domain and hardware
meaning have not been established for these profiles.

Nano defaults include a byte at file `0xB54`, but its UI property `0x6054` directly
calls hardware-facing routines `0xD74D4/0xD75A8`, with a minimum value of four in
that branch. This differs from simply assuming that a Video/Classic brightness
setting can be patched at the similar saved offset. The complete save/apply route
remains open. [Nano menu](../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000ed5d4.c).

Both full serializers overlay live EQ enable at file `0x8E0`, and copy a counted
UTF-16 active name to count `0x8EA` / text `0x8EC` only when the player's global
mode flag is set. They also overlay live volume words at file `8/12`. Those
locations are independently visible in each writer; this pass keeps the fixture's
player state matched rather than qualifying every EQ state combination. Numeric
Classic EQ IDs, a universal English-name catalog, buffer capacity and end-to-end
Off/Flat playback semantics must not be inferred from these offsets alone.

## Saved bytes versus adoption

For every updater input, the probe modifies a mocked disk file while the original
Preferences owner retains its previous payload. Its next dirty save restores the
old bytes exactly. Replacing the file again and explicitly executing the original
loader accepts the full edited payload, including an unrelated preserved byte;
the next save reproduces it. These tests prove both the stale-owner overwrite risk
and a load path, not when USB detach or reconnect triggers that path.

Static caller indexes place each reader under its loader and its owner constructor.
They do not establish whole-program absence of indirect reloads, nor guarantee a
specific eject/reset workflow. A successful Host transaction means verified saved
bytes. Physical adoption and persistence still require their own acceptance test;
restarting after a stale RAM flush may be too late to preserve the external edit.

| Target | Newly qualified | Remaining questions |
| --- | --- | --- |
| Mini 1 / 3 / 1.4.1 | 86 native cases; exact format; four common settings; language word; 50-choice saved timezone observation; load/reset/overwrite behavior | Physical adoption sequence; live clock arbitration/RTC basis; full Backlight/contrast/EQ authoring |
| Mini 1 / 6 / 1.4.1 | Separate exact input and all 86 cases | Hardware-dependent branches despite matching bytes; same live-adoption and extended-setting questions |
| Nano 1 / 14 / 1.3.1 | 39 native cases; distinct format; four common settings; language word; load/reset/overwrite behavior | Timezone/Alarm fields; physical adoption; brightness/Backlight/contrast/EQ authoring |
| Nano 1 / 17 / 1.3.1 | Separate exact input and all 39 cases | Hardware-dependent branches despite matching bytes; same clock, adoption and extended-setting questions |

Application qualification must combine model/release evidence with the exact saved
format; matching size alone does not qualify a write. Optional Preferences and
date observations remain separate from Library loading and Sync. Unknown dates,
unqualified fields and unfamiliar saved bytes stay preserved and do not become
datetime-related Library blockers.
