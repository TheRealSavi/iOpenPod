# Latest Nano 3, 4 and 5 Preferences

Investigated 2026-11-07 against retained Apple firmware, with independent native
execution for each image. **Nano 3 and Nano 4 qualify five binary Preferences
editors: Shuffle, Repeat, EQ, Sound Check and Brightness. Nano 5 qualifies
Brightness and Sound Check through a separate named XML store.** A matching
binary layout is not sufficient to select the active settings store.

No physical device I/O, USB disconnect, complete boot or live adoption was tested.
Unqualified fields, unknown values and clock bytes must survive unrelated edits.
Datetime uncertainty remains nonblocking.

## Exact latest targets

The freshly retrieved [Apple version catalog][catalog] and retained
[IPSW manifest audit][manifest-audit] identify these latest official targets.
The catalog SHA-256 is
`5a2938b0aa28808cb738b0871e01d6e084c5f56243d69b0c6c4fabec442586b8`.
The [selected entries][selected] retain the official source and download URLs.

| Target | Updater family | Latest release | Retained binary Preferences frame | Authoring store established here |
| --- | ---: | --- | --- | --- |
| Nano 3 | 26 | 1.1.3 | 2,952 bytes / first LE32 `0x3c` | `iPod_Control/Device/Preferences` |
| Nano 4 | 31 | 1.0.4 | 2,960 bytes / first LE32 `0x3e` | `iPod_Control/Device/Preferences` |
| Nano 5 | 34 | 1.0.2, build 34A20020 | 2,960 bytes / native defaults `0x3e` | `iPod_Control/Device/iPodSettings.xml` |

The Nano 5 binary frame remains an observation. Its corresponding settings UI
uses a named settings service; no bridge qualifying edits to the analogous binary
fields was established. Its XML target must not inherit Nano 4's reset-word rule.

| Image | SHA-256 |
| --- | --- |
| `Nano3FW/decrypted/osos.bin` | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` |
| `Nano4FW/decrypted/osos.bin` | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` |
| `Nano5FW/firmware/decrypted/osos.raw.bin` | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` |

Nano 3 and Nano 4 each use their own `evidence/runtime-map.json`. Their main DRAM
mappings begin at `0x08000000` from source offsets `0xf8dc` and `0xe800`,
respectively. Nano 4's uncertain final plaintext interval is excluded by native
read/fetch guards. Nano 5 maps source `0..0xe27c` at `0x22000000`, the next
`0x20000` bytes at `0x22030000`, and source `0x2e27c`, length `0x6c43a8`, at
`0x08000000`. [Nano 3 execution][nano3-native], [Nano 4 execution][nano4-native],
[Nano 5 execution][nano5-binary]

## Nano 3 and Nano 4 saved fields

All offsets below are relative to the **first byte of the Preferences file**.
Both firmware owners embed that payload at runtime owner `+4`; the settings
library stores its owner pointer at `+0xce8`. These runtime offsets are not file
offsets. Multibyte saved fields are little-endian.

| Setting | File field | Qualified authoring domain and preservation rule |
| --- | --- | --- |
| Shuffle | `0x18` u8 enabled; `0x8a` u8 album grouping | Off, Songs, Albums correspond to pairs `0/0`, `1/0`, `1/1`. Native already-Off can retain its irrelevant album byte. Preserve malformed boolean bytes on unrelated edits. |
| Repeat | `0x14` u32 | Saved domain `0,1,2`; native menu indices `0,1,2` store `0,2,1`, respectively. Keep the saved-word versus menu-index distinction used by the existing Repeat model. Unknown words remain raw. |
| EQ | `0xb60` u16 | Off `0`, preset IDs `100..121`; native menu indices `0..22`. Unknown full words display as index zero but remain full words until explicitly changed. |
| Sound Check | `0xb16` u8 | Off `0`, On `1`. Other saved bytes remain preserved when another setting changes. |
| Brightness | `0xb54` u8 | Inclusive native slider units `0..100`; independently executed wheel-handler clamps on both images. No luminance calibration is implied. |
| Clicker, observed only | `0xafc` u32 | The combined native menu can set low-two-bit values `1,2,3,0`, retaining the upper 30 bits. Individual route labels and ordinary visible-menu availability are not fully qualified here. Exclude this field from the new editor. |
| Language, observed only | `0xaf8` u32 | Full-word native getter, not an eight-bit language projection. A complete resource-dependent language catalog and reload contract remain open. |
| Backlight, observed only | `0xaf0` u32 | Native selector getter/setter. Tested scalar values are not a proven menu domain or timeout-in-seconds mapping. |

The native Repeat probes establish the numeric menu/save mapping; this pass does
not claim a complete new translation-resource audit. The existing
[Classic saved-versus-menu interpretation][classic] remains the application
terminology reference. Clicker's individual routes receive no borrowed Mini,
Video or Classic labels.

The original Settings property callback directly calls the saved setters on
both images: [Nano 3 `0815de94`][nano3-ui] uses the library pointer at UI object
`+0xb0`; [Nano 4 `08141324`][nano4-ui] uses UI object `+0xa8`. Thus the scalar
functions are linked to actual Settings operations, unlike the unqualified
binary-to-named-store relationship found on Nano 5.

| Function role | Nano 3 ARM address | Nano 4 Thumb address |
| --- | --- | --- |
| Shuffle get / set | `080347b8` / `080474b8` | `08046998` / `08059fb0` |
| Repeat get / set | `080344a4` / `080473dc` | `08046784` / `08059f16` |
| Sound Check get / set | `08034940` / `08047898` | `08046b2a` / `0805a2b4` |
| EQ get / set | `08031884` / `08046db4` | `08044906` / `0805999e` |
| EQ menu index to saved ID | `0806b968` | `0807cd84` |
| Brightness get / set | `08031288` / `08046cac` | `080443c4` / `08059876` |
| Brightness wheel clamp | `081df3d4` | `081aa74c` |
| Clicker get / set | `08031180` / `08046bec` | `080442d4` / `080597d8` |
| Language getter | `080332e4` | `08045bc8` |
| Backlight get / set | `0803119c` / `08046c90` | `080442fa` / `08059856` |

Exact byte spans, hashes, executed addresses and mocked call boundaries are in
the [Nano 3 scalar receipt][nano3-native], [Nano 3 persistence receipt][nano3-persistence]
and [Nano 4 receipt][nano4-native]. Addresses in this table are runtime addresses,
not raw image offsets.

## Binary framing, reset and publication

| Function role | Nano 3 | Nano 4 | Nano 5 observation |
| --- | --- | --- | --- |
| Payload defaults | `080a3540` | `080adc70` | `081acbc4` |
| File reader | `0808ca40` | `08098d28` | `08034e3c` |
| Owner load/init | `08043678` | `08055f10` | `080254e8` |
| Full-payload writer | `0805121c` | `08062668` | `081533c0` |
| Owner dirty byte | `+0xb8c` | `+0xb94` | `+0xb94` |

Nano 3 and Nano 4 initialize defaults, read the file and test the first two saved
u32 words. A zero version or **nonzero file `+4`** invokes native defaults.
The current-frame load path also forces file bytes `0x91`, `0xb0a` and `0xb0b`
to one. The tests distinguish those native load-time changes from host codec
preservation; a host must not normalize those bytes on an unrelated edit.
Future version words pass this particular native loader, but they do not qualify
an application authoring profile. [Nano 3][nano3-persistence], [Nano 4][nano4-native]

The writers copy the complete payload to a temporary buffer and replace saved
u32 `+8` with the queried live volume value before serialization. Apart from
that live value, exercised native output preserves the copied payload. No checksum
recalculation occurs in the inspected writer bodies. This is bounded code-path
evidence, not a claim about every firmware component or external publication
protocol. A host codec should preserve `+8` during unrelated edits.

Nano 5 differs: its bounded loader retains tested version words `0`, `0x3d`,
`0x3e`, `0x3f` and a nonzero second word. The traced load/init seam does not
implement the Nano 3/4 reset test. Its dedicated reset entry `080e3e34` is a
separate operation. **The meaning of a nonzero Nano 5 binary `+4` remains
unqualified**, including any treatment later in startup. The binary writer
still copies 2,960 bytes and overlays the live volume at `+8`.
[Nano 5 binary receipt][nano5-binary]

These reads and writes use memory-backed filesystem adapters. They establish
saved representation and local code behavior. They do not establish when USB
exit reloads externally changed files, whether a later in-memory flush overwrites
them, or whether a restart is required. File readback and live adoption remain
separate application concepts.

## Nano 5 named settings

The native constructor and saver independently establish the root
`iPodSettings` and path `iPod_Control/Device/iPodSettings.xml`. Native serialization
uses root version `1.0`, grouped named settings, and decimal scalar text.
[Named settings receipt][nano5-named]

| Qualified key | Native value/domain | Observed constructor default |
| --- | --- | --- |
| `General.Brightness` | Integer `0..100` | `40` |
| `Playback.SoundCheck` | Boolean; serialized decimal `0` / `1` | `0` |

Defaults here describe native constructor behavior. They are not permission to
create a missing settings file, discard imported unknown elements or replace an
invalid imported value automatically. The current application authoring policy
must remain explicit and lossless.

The original General constructor `08328818` and Playback constructor `08040978`
register these settings. The named service constructor is `0802f9d8`;
integer setter `08052db8` and boolean setter `08052cf0` receive the Nano 5
pointer-to-value ABI. Serializer `08063238` is reached through vtable
`08537324 +0x74`; scalar helper `08275e94` emits decimal text. Loader `08059ab0`
and saver `081ec174` establish the filename construction. These entries were
verified on Nano 5 itself, not selected by projecting Nano 6/7 vtable slots.

The UI also references named `Playback.Repeat`, `Playback.Shuffle` and
`General.Clicker` settings. Their full string domains, storage/consumer contracts
and safe editing behavior were not qualified by this bounded pass. No Nano 5
binary EQ, Shuffle, Repeat, Clicker or Brightness editor is justified by the
legacy-looking default payload. [Named probe source][nano5-named-script],
[binary probe source][nano5-binary-script]

## Evidence and reproduction

The final receipts contain **304 cases** across independently executed images:

- Nano 3: 65 scalar/getter/clamp cases and 106 EQ/load/reset/read/write cases.
  The Settings-to-scalar linkage is static; the EQ initialization, accessors and
  persistence paths execute original ARM instructions.
- Nano 4: 92 cases, including 19 original Settings callback → scalar setter →
  full serializer cases, seven brightness clamp vectors and six loader cases.
- Nano 5: 19 binary observation cases and 22 named-store cases. Registration,
  native scalar setters and serialization execute original Thumb instructions;
  collection services, locking, XML writer operations and filesystem services
  have explicit memory adapters.

Allocation, file access, player services and notification endpoints are mocked
as listed in each receipt. UI navigation, speaker routing, physical backlight
output and complete boot are outside the native tests. A separate
[export byte audit][export-audit] matches 154 Nano 3 and 201 Nano 4 assembly
exports against their exact mapped inputs, totaling 18,044 and 12,532 verified
instruction bytes respectively; repeated exports are counted separately.
Function recovery used isolated copies of the Nano 4/5 Ghidra projects, preserving
the original projects and binaries.

Run from the firmware lab with new output directories:

```powershell
uv run scripts/check_nano3_preferences_settings.py --output artifacts/nano3-settings-next
uv run scripts/check_nano3_preferences_persistence.py --output artifacts/nano3-persistence-next
uv run scripts/check_nano4_preferences.py --output artifacts/nano4-settings-next
uv run scripts/check_nano5_preferences.py --output artifacts/nano5-binary-next
uv run scripts/probe_nano5_named_preferences.py --output artifacts/nano5-named-next
```

Nano 3's persistence wrapper pins and calls the unchanged Classic harness,
independently discovering and executing Nano 3 instructions. Its receipt records
both helper and wrapper hashes. Final receipt SHA-256 values for the new Nano 3/4
probes are:

| Receipt | SHA-256 |
| --- | --- |
| Nano 3 scalar | `f60f486d0aa65cf361bec5d842ec2bcfc4a3a772b6071f885bfaa61cea9e02e9` |
| Nano 3 persistence | `c56953a080a0597ea1f04ea268e50600cd28e31aa2615ad255a7feed871560c7` |
| Nano 4 | `23af79c7427a936670c7c694a694408272569ae207aaa5761fde60f77b0299f1` |

## Remaining questions

1. **All three:** resolve USB disconnect, disk-mode exit, reboot and later dirty
   flush ordering. Saved-file validity does not settle external-edit adoption.
2. **Nano 3/4:** bind Clicker's individual routes and visible options to the
   resource catalog and actual output consumer; finish Backlight durations,
   language choices and Main/Music menu bit catalogs before offering those edits.
3. **Nano 3/4:** qualify clock fields separately. This pass neither validates the
   historical generic Nano 3 `0x6bc` DST projection nor substitutes Classic city,
   prefix or saved-DST interpretations at `0xb6c` and neighboring fields.
4. **Nano 5:** close the remaining named string-setting domains and their
   notification/persistence behavior; determine whether any binary settings still
   drive user-visible preferences, and whether another startup stage interprets
   its first two words.
5. **All three:** a native default, neighboring scalar field or successfully
   executed low-level setter does not establish a complete user-facing domain.
   Preserve that distinction as additional fields are added.

[catalog]: ../../../ipod-firmware-lab/artifacts/preferences-latest-catalog-20261107/apple-version-catalog.plist
[selected]: ../../../ipod-firmware-lab/artifacts/preferences-latest-catalog-20261107/selected.json
[manifest-audit]: ../../../ipod-firmware-lab/artifacts/preferences-latest-catalog-20261107/manifest-audit.json
[classic]: preferences-classic-writes-2026-11-07.md
[nano3-native]: ../../../ipod-firmware-lab/artifacts/preferences-nano3-native-20261107-final/receipt.json
[nano3-persistence]: ../../../ipod-firmware-lab/artifacts/preferences-nano3-persistence-20261107-final/receipt.json
[nano3-ui]: ../../../ipod-firmware-lab/artifacts/preferences-nano26-fields-20261107/0815de94.c
[nano4-native]: ../../../ipod-firmware-lab/artifacts/preferences-nano4-native-20261107-final/receipt.json
[nano4-ui]: ../../../ipod-firmware-lab/artifacts/preferences-nano31-ui-20261107/08141324.c
[nano5-binary]: ../../../ipod-firmware-lab/artifacts/nano5-preferences-native-20261107-v2/receipt.json
[nano5-named]: ../../../ipod-firmware-lab/artifacts/nano5-named-preferences-20261107-v3/receipt.json
[nano5-binary-script]: ../../../ipod-firmware-lab/scripts/check_nano5_preferences.py
[nano5-named-script]: ../../../ipod-firmware-lab/scripts/probe_nano5_named_preferences.py
[export-audit]: ../../../ipod-firmware-lab/artifacts/preferences-nano34-export-audit-20261107.json
