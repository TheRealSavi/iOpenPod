# iPod EQ firmware research

Research date: 2026-11-06. This investigation distinguishes firmware behavior
from Apple's user-facing descriptions and from Host playback behavior. Firmware
claims must remain qualified to the inspected model and RetailOS build.

The follow-up [implementation-readiness report](ipod-eq-implementation-readiness.md)
maps these findings to Settings, Track viewing/editing, Sync, and publication.

## Findings from the actual firmware

The primary evidence is the local **ipod-firmware-lab**, including original ARM
instructions, corrected Ghidra function signatures and boundaries, and bounded
native execution. Apple manuals below are corroboration. No firmware was flashed,
no physical device was changed, and no listening or complete OS-boot test was run.
[Lab investigation][lab-eq], [cross-build comparison][comparison],
[native execution receipt][native]

The four inspected Classic releases have the same tested selection rule:

1. Read the device's EQ setting and map it to a DSP preset.
2. If the device setting is **Flat**, retain Flat regardless of the Track setting.
3. Otherwise, a nonzero Track EQ byte replaces the device setting.
4. A missing/zero Track setting leaves the device setting in effect.

Thus Track Jazz overrides device Rock as well as device Off. Off does not mean
"ignore Track EQ." Flat means a neutral preset that overrides Track EQ, and is
implemented differently from the DSP bypass selected by Off.
[Native selection][native], [Classic 2.0.1 DSP probe][native201]

The other major finding is the **Track representation**: Classic's iTunesDB
MHOD type 7 import path consumes marked numeric strings such as `#!#100#!#`
(Acoustic), `#!#107#!#` (Flat), and `#!#116#!#` (Rock). Plain `Acoustic`, `Flat`,
`Rock`, and an arbitrary custom name all produce a zero Track EQ value in the
tested importer callback. The firmware's separate preset-name lookup belongs to
an older Preferences migration path; finding that lookup does not establish
name-based Track EQ. [Lab import trace][lab-eq], [native marker cases][native]

## Evidence scope and exact images

These are the lab's retained decrypted OSOS images. Addresses in the investigation
are runtime virtual addresses, not raw file offsets. Each comparison and native
run checks the image hash and uses its own startup-derived memory map. Updater
family and release identify the build; retail generation shorthand does not.
[Comparison receipt][comparison], [Classic identity evidence][classic-targets]

| Updater family | RetailOS | OSOS SHA-256 |
| --- | --- | --- |
| 24 | 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` |
| 33 | 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| 35 | 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` |
| 38 | 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |

The cross-build harness executes 576 global/Track combinations,
41 string import cases, and 138 DSP-preset/sample-rate combinations **per build**: 3,020 native
cases across four builds. It mocks the final audio-command dispatch, Track
view validity, and ASCII-only UTF-16 conversion. The native selector, marker
checks, decimal parser, stored result, DSP mapper, and coefficient loader execute
from the original images. This does not execute a complete iTunesDB import,
firmware event loop, sample-processing loop, audio hardware, or Unicode conversion.
All four builds produce equal results for the tested cases. [Harness][harness],
[native receipt][native]

The full MHOD7-to-callback binding is traced in Classic 2.0.1. The other three
builds independently execute the corresponding callback and playback routines;
that is narrower than proving their complete database-import lifecycle. Static
relocation matching discovers candidates; native execution and explicit table
comparisons provide the stronger evidence reported here. [Comparison][comparison]

## Keep the EQ representations separate

| Representation | Meaning and evidence |
| --- | --- |
| Device EQ preference | Firmware-owned default selection in `iPod_Control/Device/Preferences`; separate from iTunesPrefs and Host settings. |
| Menu index | Classic menu position: 0 for Off, 1–22 for named built-ins. |
| Settings ID | 0 for Off; 100–121 for the built-ins. Stored Preferences and imported Track values use this namespace. |
| Per-Track EQ text | MHOD7's marked numeric representation, such as `#!#116#!#`; it is not the curve itself. |
| DSP preset | Compact 0–22 selector: settings IDs 100–121 map to 1–22; everything else maps to zero. |
| Custom Host preset | An iTunes-created name and curve; creating or assigning it on the Host does not establish device support. |
| `EQPresets` file | A separate historical artifact name; no consumer is established in the inspected Classic path. Do not conflate it with Preferences or MHOD7. |

The namespace distinction is directly visible in the menu table, Preferences
setter, importer, and DSP mapper. [Classic 2.0.1 native receipt][native201],
[lab trace][lab-eq]

### Built-in presets

The Classic 2.0.1 menu table at `083d2a7c` has 23 entries. The name-migration
routine and its literal-name block match across all four builds. The complete
DSP mapping also executes identically. These names are useful display labels;
they are not the observed MHOD7 encoding. [Menu and mapping][native201],
[cross-build comparison][comparison]

| Name | Settings ID | Menu/DSP index | Tested marked Track value |
| --- | ---: | ---: | --- |
| Off / no Track override | 0 | 0 | No MHOD7, or `#!#000#!#` yielding zero |
| Acoustic | 100 | 1 | `#!#100#!#` |
| Bass Booster | 101 | 2 | `#!#101#!#` |
| Bass Reducer | 102 | 3 | `#!#102#!#` |
| Classical | 103 | 4 | `#!#103#!#` |
| Dance | 104 | 5 | `#!#104#!#` |
| Deep | 105 | 6 | `#!#105#!#` |
| Electronic | 106 | 7 | `#!#106#!#` |
| Flat | 107 | 8 | `#!#107#!#` |
| Hip Hop | 108 | 9 | `#!#108#!#` |
| Jazz | 109 | 10 | `#!#109#!#` |
| Latin | 110 | 11 | `#!#110#!#` |
| Loudness | 111 | 12 | `#!#111#!#` |
| Lounge | 112 | 13 | `#!#112#!#` |
| Piano | 113 | 14 | `#!#113#!#` |
| Pop | 114 | 15 | `#!#114#!#` |
| R & B | 115 | 16 | `#!#115#!#` |
| Rock | 116 | 17 | `#!#116#!#` |
| Small Speakers | 117 | 18 | `#!#117#!#` |
| Spoken Word | 118 | 19 | `#!#118#!#` |
| Treble Booster | 119 | 20 | `#!#119#!#` |
| Treble Reducer | 120 | 21 | `#!#120#!#` |
| Vocal Booster | 121 | 22 | `#!#121#!#` |

This table describes the firmware contract, not an implemented iOpenPod writer
policy. Unknown source bytes still require preservation under ADR-0006.

### Preferences and runtime state

In Classic 2.0.1, saved EQ is a little-endian u16 at Preferences **file offset
`0xb60`**, accessed at runtime context `+0xb64` because the serialized payload
starts at context `+4`. Setter `0804573c` converts menu position to settings ID,
compares/stores that u16, marks Preferences dirty, and sends its low byte to the
player. Runtime player state keeps the selection separately from the saved file.
The UI therefore does not directly rewrite an EQ curve or MHOD7 on each Track.
[Lab Preferences trace][lab-eq]

The 2.0.1 initializer writes zero (Off). Its loader migrates versions below
`0x34` from a counted UTF-16 preset name at payload `+0x8ea`; that lookup is
case-sensitive and maps unrecognized names to zero. Unknown saved IDs display
as menu position zero without proving the saved word was rewritten. Independent
setter probes cover 69 cases: unchanged values remain clean, and changes dirty
Preferences and update the player request. [Initialization and migration][lab-eq],
[Preferences setter execution][native201]

Corresponding setter bodies at `0804455c`, `0805c07c`, and `0805c0b8` retain the
same u16 field access for families 24, 35, and 38. The later two differ in the
owning object's Preferences-pointer offset (`+0xf00` instead of `+0xce8`), so
blindly copying object offsets would be wrong. The follow-up executes **424
additional native cases**, covering all four builds' getter, menu mapping,
setter, defaults, loader, player initialization and whole-payload saver. It
independently confirms file offset `0xb60` and the four exact writer extents and
versions. Existing exact-layout/profile qualification remains necessary.
[Preferences follow-up][preferences-followup], [native receipt][preferences-native],
[Preferences contract](../ipod-preferences.md)

The saved word, menu label and player byte are distinct. All four menu getters
compare the full u16, but player initialization sends its low byte. Saved 356
therefore displays the Off fallback while initializing Acoustic/100; saved 363
displays Off while initializing Flat/107. A nonzero u32 at file `+0x04` instead
causes the loader to reset Preferences, including EQ. A precise view must retain
these conditions rather than label every unknown word Off.
[Native read/load/initialization cases][preferences-native]

The saver copies retained RAM to the complete file without merging intervening
Host edits. A modeled Host patch from Jazz to Rock is overwritten by a later
dirty flush of the old Jazz context. This establishes the overwrite mechanism,
not the actual ordering at disconnect or disk-mode exit. A successful Host write
and readback do not establish device adoption or persistence.
[Lifecycle and publication boundary][preferences-followup]

### Exact selection examples

These examples use valid Track views and a media kind admitted by the selection
routine. The Classic 2.0.1 predicate admits native object kinds 3 and 4; these are
internal runtime kinds, not a new mapping of iTunesDB media-type bits.
[Predicate cases][native201], [native selection cases][native]

| Device preference | Track EQ | Effective choice |
| --- | --- | --- |
| Off | Missing / zero | DSP bypass |
| Off | Rock, encoded as `#!#116#!#` | Rock |
| Jazz | Missing / zero | Jazz |
| Jazz | Encoded Rock | Rock |
| Flat | Encoded Rock | Flat |
| Rock | Encoded Flat | Flat |
| Rock | Plain text `Acoustic` | Rock: the importer produces zero |
| Rock | Encoded unknown nonzero byte, e.g. 255 | DSP zero: unknown Track ID overrides the global selection, then fails built-in mapping |

The importer is permissive, not a strict nine-character validator. It checks
leading and trailing `#!#`, copies three bytes of converted text after the leading marker,
parses a decimal prefix, and stores a u16. Playback reads only the low byte.
Native examples include `#!#100extra#!#` → 100, `#!#1x0#!#` → 1,
`#!#12#!#` → 12, `#!#356#!#` → u16 356 → playback byte 100, and
`#!#256#!#` → playback byte zero. A missing marker or text after the closing
marker produces zero. These are preservation/research observations, not suggested
encodings for new writes. [Marker execution cases][native]

## DSP implementation and custom-preset boundary

Classic's inspected loader uses compiled coefficient tables and up to three
filter sections per DSP preset. Both 54-record coefficient tables (44.1 and
48 kHz, 1,080 bytes each) and the 23-by-3 signed section-index table (276 bytes)
match **byte for byte** in all four images. A section index of -1 is bypassed.
This is a fixed preset bank, not a ten-slider custom-curve interface.
[Table hashes and locations][comparison], [coefficient loader cases][native]

DSP zero disables this effect. Flat is DSP 8, selecting coefficient record 17
and bypassing the other two sections. Its numerator and denominator coefficients
are equal, giving a mathematically flat response, but the effect-enable byte
remains set for 44.1/48 kHz. Do not equate mathematical flatness with the bypass
branch or claim sample-exact identity without executing fixed-point processing.
The loader disables this effect for other supplied processing rates. That does
not prove that a source file at another rate bypasses EQ: upstream resampling
and routing remain outside these probes. [Flat coefficients][native201],
[four-build loader execution][native]

An arbitrary Track name has no custom-curve path in this import/selection chain.
An out-of-range numeric ID does not allocate a new preset; after low-byte
projection it either aliases a built-in, becomes zero, or maps to DSP zero.
No NUL-terminated ASCII `EQPresets`/`iTunesEQPresets` filename appears in the four inspected OSOS images,
and no external-preset reader was found in the traced path. String absence alone
does not prove that every module, resource, earlier generation, or firmware lacks
such a reader. The supported conclusion is **fixed built-in selection in the
qualified native paths**, with custom-file support unestablished.
[Native imports][native], [string survey][comparison]

Sound Check, Track relative volume, volume limits, and EQ have separate metadata
and controls. This investigation does not establish their complete gain ordering,
clipping behavior, processing cost, or interaction with every codec and output.

## Nano 5 has a separate SQLite text parser

The independently inspected nano 5 RetailOS **1.0.2** image has SHA-256
`dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49`.
Its initialized runtime regions were verified against that image before analysis.
The native Thumb getter at `081b2f0c` obtains `item.eq_preset` text through
`081602e4` and the column-24 accessor at `0816a7fe`. Runtime provider mode at
`+0x461` gates access; it is not an on-disk EQ-presence flag. It scans the entire
string, retains ASCII decimal digits
through predicate `0815f428`, parses the accumulated digits, and truncates to u8.
It does **not** require Classic's boundary markers or three-byte numeric extent.
[Nano/Video lab trace][nano-video], [native Nano 5 probes][nano-native]

| Nano 5 SQLite EQ text | Returned settings byte |
| --- | ---: |
| Empty, `Rock`, or `Acoustic` | 0 |
| `#!#114#!#`, `114`, `a1b1c4`, or `-114` | 114 / Pop |
| `107` | 107 / Flat |
| `356` | 100 / Acoustic |
| `999` | 231 / unknown |
| `Rock2` | 2 / unknown |
| Present text with provider mode zero | 0 |

Native selector `0824c2e8` has the same effective precedence: device Flat/107
prevents a Track override; otherwise a nonzero Track byte takes precedence.
Settings IDs 100–121 map to DSP 1–22, and an unknown nonzero Track ID can override
a valid global setting with DSP zero. The 23-entry menu conversion separately
uses 0 and 100–121. [Nano 5 native cases][nano-native], [lab mapping trace][nano-video]

The Nano 5 harness passes **12 text-getter cases and 30 selection cases** using
the original instructions. It mocks object validity, row/string services and
audio submission; the column index is checked at the mocked SQLite access seam.
This does not exercise a real SQLite engine, all Unicode/numeric-overflow cases,
firmware startup, the full saved Preferences format, or Nano 5's DSP coefficients.
The shared preset names and selector behavior must not be used to copy Classic
Preferences offsets or its coefficient banks into Nano support. [Harness][nano-harness]

A follow-up executes the native lazy accessor, virtual row dispatch, column-24
cell access, constructors and cleanup in **16 additional probe outcomes**. The
mode byte originates in provider construction and gates several metadata getters.
An existing cached row keeps its old EQ after a modeled external source change;
the actual firmware reload event remains unqualified. NULL string pointers and
unavailable typed cells return zero, without proving every SQLite NULL hydration
rule. [Cached-row investigation][nano-publication], [follow-up receipt][nano-publication-native]

Nine reviewed Nano 5 names/comments were saved in its runtime Ghidra project,
and 396 exported instruction bytes were compared with the original image. The
settings-to-DSP routine uses an inline Thumb switch table: its naive decompilation
misread table bytes as code, while native execution resolves the actual mapping.
[Deobfuscation and verification][nano-video]

## Nano 3/4 extension and remaining family coverage

Nano 3 family 26 / **1.1.3**, SHA-256
`ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a`,
independently passes **755 additional native cases**: the same 576 selection,
41 string-import, and 138 coefficient-load cases as Classic. The complete tested
results and all three compiled tables match Classic 2.0.1. Its outer MHOD7 caller
binding and complete persistence lifecycle remain untraced. The wrapper records
all reused script hashes and separately verifies Nano 3 results against the
Classic control; it does not substitute a Classic image for Nano firmware.
[Nano 3 receipt][nano3-native], [wrapper provenance][nano3-manifest],
[Nano 3/4 lab note][nano34-note]

Nano 4 family 31 / **1.0.4**, SHA-256
`a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372`,
contains identical coefficient banks at `0838b64c` and `0838ba84` and the same
section-index table at `0838bebc`. Complete Classic function signatures did not
match this build, so this establishes retained table data, not their reachable
consumers or actual EQ precedence. No Nano 4 native EQ execution is claimed.
The survey excludes the map's uncertain trailing eight bytes.
[Static survey][nano34-static], [lab scope][nano34-note]

| Firmware family | Strongest evidence from this investigation | Still unresolved |
| --- | --- | --- |
| Classic 24/33/35/38 | Native selection, string callback, coefficient loads and Preferences read/load/set/save on four exact releases; detailed 33 import trace | Full event routing, physical playback, complete outer import and device reload/flush ordering |
| Nano 3 / 26 | Native callback, selection and coefficient loads | Outer import binding, complete Preferences lifecycle |
| Nano 4 / 31 | Byte-identical compiled tables | Native consumers, Track parser, Preferences and precedence |
| Nano 5 / 34 | Native cached-row text getter, provider construction and selector; UI/property traces | Serialized EQ Preferences offset, DSP coefficient route, SQLite hydration and device reload event |
| Video / 13/20/25, 1.3 | Follow-up executes MHOD7 `resm` normalization, registry lookup, menu/Track selection, audio command submission and Preferences; normal coefficient banks match Classics | Complete playback lifecycle, Off/manual discrepancy, physical adoption and custom-file reader |
| Mini 2 / 7, 1.4.1 | Follow-up executes registry, callback, menu/Track selection, Preferences and lower normal-bank loading | Complete playback lifecycle, Off/manual discrepancy, physical hardware-bank selection and custom-file reader |
| Earlier full-size, Mini 1, nano 1/2/6/7, other builds | No new native EQ qualification in this pass | Independent firmware evidence rather than inheritance from a similar model |

The initial Video finding was limited to `000fb7b8`'s `resm` name conversion,
documented in the [Nano/Video note][nano-video]. The subsequent
[older-device comparison](ipod-eq-evolution-and-device-support.md) binds this
callback to the actual MHOD7 importer and name-based playback registry on all
three Video images, with an independent Mini 2 investigation. This remains
different from Classic's `rsid` numeric importer. In particular, older global
Flat does not suppress a valid Track override in the tested path.

## iOpenPod compatibility finding

At investigation baseline `0eeff3fdd19ac0e770f24b086fa63a33014643cd`, the common
Library exposes `metadata.equalizer` as a string, maps it directly to MHOD7, and
also publishes that string to SQLite `item.eq_preset`. The metadata editor offers
it as text. A projection fixture uses `Acoustic`, demonstrating preservation of
that string rather than firmware acceptance of it.
[Field mapping][field-policy], [SQLite writer][sqlite-writer],
[metadata fields][metadata-fields], [existing test][projection-test]

Original iOpenPod at `a20242428b93b672d14b37230772dbad75139c69` likewise describes
the field as a preset name and writes it directly. **That inherited description
disagrees with the now-executed Classic importer.** A user entering a built-in
name can obtain a correctly serialized string that the Classic then interprets
as no Track EQ. Existing marked strings can already be retained; retaining them
is not equivalent to offering a correctly encoded preset editor.
[Original field declaration][original-field], [Original writer][original-writer],
[native marker cases][native]

This research makes no application behavior change. Follow-up implementation
should separate a display label/semantic preset from retained raw EQ text,
qualify native authoring by firmware evidence, preserve unknown values, and test
the resulting bytes against the native importer. Nano 5's SQLite consumer is
now independently evidenced above; later SQLite firmware still needs its own
qualification. A column named `eq_preset` does not establish a shared parser.
An EQ Preferences writer or custom-preset feature
would require its own reviewed scope and device-safe publication contract.

The [application follow-up](ipod-eq-implementation-readiness.md) now reproduces
two additional ownership issues: Sync's metadata merge can clear an iPod-only EQ
assignment from Host default-empty metadata; SQLite regeneration can replace a
saved SQL EQ with the CDB-projected value during an unrelated edit. It also
verifies retained EQ bytes across unrelated Library edits and identifies the
existing Settings, metadata editor, codec and publication seams for implementation.

## Reproduce the Classic investigation

From the sibling firmware lab, choose new output names; the scripts refuse to
replace existing evidence:

```powershell
uv run python scripts/audit_eq_classic_families.py --output artifacts/eq-comparison-next
uv run scripts/check_classic_family_eq.py --comparison artifacts/eq-comparison-next/receipt.json --output artifacts/eq-native-next.json
uv run scripts/check_classic201_eq.py --output artifacts/eq201-native-next.json
```

The [lab note][lab-eq] links the corrected Ghidra exports and annotation receipts.
Twenty-two reviewed names/prototypes are saved in the dedicated Classic 2.0.1
research project. Correcting a shared dispatcher-tail boundary and flow annotation
restored the effective-preset return values missing from the earlier pseudocode.
Fresh reopening verified the saved annotations and unchanged mapped firmware.
Firmware images and generated projects remain local lab inputs, outside the
application distribution. The standalone Classic 2.0.1 probe passes 1,086 cases,
including the setter probes, and checks the 23-entry menu round trip separately.

## Apple documentation baseline

The manuals below independently document a built-in EQ menu and say that a
Track's assigned iTunes preset is used when the device EQ preference is **Off**.
They establish that Off is not an unconditional request to ignore per-Track EQ.
They do **not** specify the full precedence rule when both a Track and the device
have different non-Off presets. Do not turn that omission into an exclusive
"use Track EQ only when device EQ is Off" rule. [Classic 120GB][classic120],
[Classic 160GB][classic160], [nano 4][nano4], [nano 5][nano5]

| Model and source edition | Printed page | Device menu | Documented per-Track case |
| --- | --- | --- | --- |
| Classic 120GB, Apple MA630 | 33 | Settings > EQ | Off honors the Track's iTunes preset |
| Classic 160GB, Apple MA1195 | 32 | Settings > EQ | Off honors the Track's iTunes preset |
| nano 4, Apple MA629 | 42 | Settings > Playback > EQ | Off honors the Track's iTunes preset |
| nano 5, Apple MA1194 | 47 | Settings > Playback > EQ | Off honors the Track's iTunes preset |

Apple's battery guidance separately says that **Flat** is the way to obtain the
effect of no EQ when Tracks already have iTunes EQ assignments. It also describes
EQ as playback processing that consumes additional processor work, rather than
an effect already encoded into the song. These statements support keeping Off,
Flat, and a missing Track assignment distinct. They do not establish the exact
DSP bypass branch, coefficients, CPU cost, or battery savings for a particular
firmware. [Apple battery guidance][batteries]

The guides describe Sound Check separately: it applies iTunes-derived relative
volume adjustment when enabled on the device. The presence of Sound Check, volume
limits, or Track volume adjustment must not be used as evidence for an EQ preset
or a custom EQ curve. [Classic 120GB, p. 32][classic120],
[Classic 160GB, p. 31][classic160], [nano 5, pp. 46–47][nano5]

### Host presets and custom curves

Apple's iTunes guide distinguishes the current equalizer setting, named presets
created by adjusting frequency sliders, and the preset assigned to an individual
song through its Options. It says a song assignment takes precedence over the
Host's general setting. That is evidence about **iTunes playback**; the page
does not establish that iPod firmware receives, stores, or executes an arbitrary
custom curve. [Apple iTunes guide][itunes]

The retired Apple article "iPod: About the Equalizer" (`artnum=61567`) could not
be retrieved from its original endpoint during this pass. Its often-repeated
custom-preset prohibition is therefore not adopted here as independently
verified primary evidence. Native code and a reproducible input/output experiment
must settle the actual support and fallback behavior for each inspected build.

### Family and interpretation limits

Manual editions identify products, not the exact firmware build installed on an
individual device. Agreement between these manuals does not prove shared offsets,
preset IDs, DSP tables, or behavior on full-size generations 1–5.5, Mini, or every
Nano. Shuffle and touch are outside the repository's release target under
[ADR-0004](../adr/0004-use-original-iopenpod-as-the-compatibility-baseline.md);
their behavior should not be used to fill gaps in the supported families.

The title of Apple's battery section groups shuffle, nano, and classic, but the
text also mentions controls absent from some of those devices. That grouping
alone cannot establish Shuffle EQ support. [Apple battery guidance][batteries]

## Primary documentation sources

All sources below were accessed on 2026-11-06. PDF page references use the printed
page number, which is one greater than the zero-based PDF page index for the
four linked manuals.

- [Apple Classic 120GB User Guide, MA630][classic120], pp. 32–33.
- [Apple Classic 160GB User Guide, MA1195][classic160], pp. 31–32.
- [Apple nano 4 User Guide, MA629][nano4], p. 42.
- [Apple nano 5 User Guide, MA1194][nano5], pp. 46–47.
- [Apple battery performance guidance][batteries], iPod EQ paragraph.
- [Apple iTunes sound-quality guide][itunes], global, custom, and per-song EQ.

[classic120]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf
[classic160]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma1195_ipod_classic_160gb_user_guide.pdf
[nano4]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma629_ipod_nano_4th_gen_userguide.pdf
[nano5]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma1194_ipod_nano_5th_gen_userguide.pdf
[batteries]: https://www.apple.com/batteries/maximizing-performance/
[itunes]: https://support.apple.com/en-lk/guide/itunes/itns2991/windows
[lab-eq]: ../../../ipod-firmware-lab/Classic33FW/notes/itunesdb/eq-overview.md
[comparison]: ../../../ipod-firmware-lab/artifacts/eq-classic-families-20261106-final/receipt.json
[native]: ../../../ipod-firmware-lab/artifacts/eq-classic-families-20261106-native-final-v3.json
[native201]: ../../../ipod-firmware-lab/artifacts/eq201-native-20261106-final.json
[harness]: ../../../ipod-firmware-lab/scripts/check_classic_family_eq.py
[classic-targets]: classic-latest-firmware-targets-2026-11-05.md
[field-policy]: ../../src/iPodDB/library/_field_policy.py
[sqlite-writer]: ../../src/iPodDB/SQLiteDB/database.py
[metadata-fields]: ../../src/iOpenPod/app/metadata_fields.py
[projection-test]: ../../tests/iPodDB/library/test_library.py
[original-writer]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhod_writer.py#L571
[original-field]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhit_writer.py#L121
[nano-video]: ../../../ipod-firmware-lab/notes/eq-nano-video.md
[nano-native]: ../../../ipod-firmware-lab/artifacts/eq-nano-video-20261106/nano5-native-probes-v2.json
[nano-harness]: ../../../ipod-firmware-lab/scripts/probe_eq_nano5.py
[nano3-native]: ../../../ipod-firmware-lab/artifacts/eq-nano3-native-20261106-final/native.json
[nano3-manifest]: ../../../ipod-firmware-lab/artifacts/eq-nano3-native-20261106-final/extension-manifest.json
[nano34-static]: ../../../ipod-firmware-lab/artifacts/eq-nano34-20261106-final/receipt.json
[nano34-note]: ../../../ipod-firmware-lab/notes/eq-nano34.md
[preferences-followup]: ../../../ipod-firmware-lab/notes/eq-preferences-configuration.md
[preferences-native]: ../../../ipod-firmware-lab/artifacts/eq-preferences-native-20261106-final/receipt.json
[nano-publication]: ../../../ipod-firmware-lab/notes/eq-nano5-publication.md
[nano-publication-native]: ../../../ipod-firmware-lab/artifacts/eq-nano5-config-20261106/native-publication-probes-v2.json
