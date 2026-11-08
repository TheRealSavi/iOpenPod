# Video 5/5.5 preferences: volume, photo, radio and cache consumers

Research date: 2026-11-07. This continues the
[whole-file inventory](preferences-video-complete-2026-11-07.md) for the latest
Video firmware **1.3**, updater families **13, 20 and 25**. It closes several
consumer questions without claiming an exhaustive Preferences decoder. All work
was offline; no device was accessed and no application writer was enabled.
Datetime uncertainty remains non-blocking.

## Inputs, receipts and coverage

Families 13 and 20 independently load OSOS SHA-256
`f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7`.
Family 25 independently loads
`784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251`;
its first 7,559,680 bytes match, followed by 1,536 zero bytes. This equivalence
does not replace the per-input native runs or source checks.

The [final native receipt][receipt] contains **24,390 passing cases**, 8,130 per
input, and hashes **1,594 executed original four-byte instructions per input**.
The firmware's own startup copy/zero routine initializes runtime memory through
the pinned `sidb_video_native.py` helper. Adapters supply filesystem buffers,
resource/service boundaries, synthetic playlist/provider state, and callback
targets. Cache pool allocation, radio hardware, actual audio output and lock-file
I/O are not physical observations.

Every preference mutation checks the entire 2,924-byte serialized file against
the prior payload, permitting changes only to the identified field or coupled
fields. Read-only consumer cases check complete preservation. Lock-record cases
also preserve the complete Preferences file, and suffix tests check the complete
32-byte record. Selected boundary and malformed values are explicit in the
receipt; the u32 space was not exhaustively enumerated.

| Case group | Per input |
| --- | ---: |
| Volume-limit consumer and bounded live volume/balance save | 552 |
| Raw u32 packing and live saves with large limits | 272 |
| Photo duration, transitions and music | 1,803 |
| Week-start store/labels and ignored decoder options | 768 |
| Radio store, converters and configuration | 3,885 |
| Artwork cache setter/callback behavior | 774 |
| Volume-lock record, provider, suffix and XOR roundtrip | 76 |

The [new full-file inventory][inventory] retains the previous final-v5 provenance
and adds this pass. Its builder validates **30,292 distinct exported instruction
bytes against each of the three originals** and records 686 static export file
hashes. It assigns 627 bytes across 54 fields, considers 559 bytes semantically
resolved, and explicitly leaves **2,297 unmapped bytes / 2,365 unresolved bytes
including partial fields**. Proved padding remains **zero**. A partial field
remains unresolved in its entirety; known low bits do not silently resolve a
whole word.

This inventory intentionally does not silently incorporate concurrent parent
research. The parent separately qualified the file `0x91` loader/cache gate and
the `0xB0B` normalized artist key path. Its latter exact binding is
`D7888` MHOD type 4 → `10DB84` → `907F4` → `1114DC` → `90D88`; getter `9FAA8`
chooses the original or alternate artist key. See the independent
[artist receipt][artist] and [metadata binding export][artist-export] when
consolidating the inventories. `0xB0A` is not inferred from that result.

The subsequent [consolidated inventory][combined] merges those two partial
consumer fields into this final-v3 inventory. It retains this report's corrected
balance arithmetic, all other field contracts and the unchanged conservative
coverage. Its separately pinned inputs preserve both investigations' provenance.

Reproduce from the sibling firmware lab, using fresh output directories:

```powershell
uv run scripts/research_preferences_video_deep_followup.py --output artifacts/NEW-native
uv run scripts/inventory_preferences_video_deep_followup.py --receipt artifacts/NEW-native/receipt.json --output artifacts/NEW-inventory
```

Final hashes:

- Native script: `5a5a5b9f403d4cfb406ab33621b2dcc7f34c55ad44349a9f9279a2b0201cb5ca`.
- Native receipt: `d000e5bcc2ddcfe94543e79d7c3ad2a8740b6c3bcf596ac5c2bcea5dea6d2b4f`.
- Inventory builder: `e8f1b2249a451dee560c612e68c5367d7741966cebfbe8d533f1fd528cee2c4f`.
- Inventory: `c53e2ddc9daf17fcfcefd9afb54d903ee18f5cd05d40a82cd8c29442840e3d41`.

`pass*` and earlier `final-v1` through `final-v5` native directories are development
or superseded checkpoints, including failed hypotheses. The authoritative native
directory is **final-v6**; the authoritative inventory directory is
**deep-fields final-v3**. This revision adds the peer-review overflow cases;
the earlier 23,574-case receipt remains unchanged.
The earlier 393-case and 27-case alarm receipts remain separate and unchanged.

## Volume words and percentage limit

The saved u32 at **`0x08`** is a device-scale master level, default 108. The u32
at **`0x0C`**, default 50, is a **stereo balance coordinate**, not another master
volume or percentage ceiling. Constructor `9421C` copies these into playback
`+276C/+2774`; the full saver overlays them back into Preferences. Playback
`+2770`, initially 256, is a separate live level used by `B348C` and is not a
third Preferences word. [Original volume export][volume-export]

For ordinary bounded level `0..512` and balance `b` in `0..100`, absent
track-specific gain adjustment, `92838` packs:

```text
low16  = level * min(50, 100 - b) // 50
high16 = level * min(50, b) // 50
```

Within those bounds, 50 leaves both channels unchanged; 0 silences the high
packed channel and 100 silences the low one. The physical left/right assignment
has not been qualified. `D1EB0` returns zero when playback `+2788` is nonzero;
otherwise it tails into `92838`. When a current
track exists, `92838` can apply a signed track adjustment before balance and
clamps the adjusted level to `0..512`; the precise gain curve remains open.
The no-track branch does **not** impose that clamp.

For raw persisted u32 words, the exact no-track arithmetic is instead:

```text
L and B are unsigned 32-bit words; M = 2^32
A = 50 if B <= 50 else (100 - B) modulo M
C = min(50, B)
Qlow  = ((L * A) modulo M) // 50   # unsigned division
Qhigh = ((L * C) modulo M) // 50   # unsigned division
packed = (Qlow OR (Qhigh << 16)) modulo M
```

The `MUL` instructions at `928EC/928FC` wrap before unsigned division through
`82694`. The `ORR` at `92904` **does not mask `Qlow` to 16 bits**. Therefore a
large low quotient can set bits in the high output half, and the shifted high
quotient can lose bits. Calling these intermediate quotients independent
16-bit channel values would be incorrect for malformed or extreme input.

For example, saved limit `FFFFFFFF`, runtime maximum 216 and enable 1 produce
ceiling **42,949,670**. With no current track, live setter `116D84` accepts
requested level **65,536** and balance 0, then emits **`00010000`**: the extracted
high half is 1, despite balance 0. The revised receipt includes 132 cases per
image running both original formatter entry points with raw u32 level/balance
words, plus 140 large-limit setter/whole-file-save cases. They cover product
wrap, unsigned division and the unmasked packing, including balance words above
100 when a raw file bypasses the live setter's balance clamp.

Setter `116D84` first compares the requested level **unsigned** against the limit
consumer, then clamps any negative signed result to zero. Consequently a raw
`FFFFFFFF` request normally becomes the ceiling, not zero. It treats balance as
signed, clamps negative inputs to 0 and values above 100 to 100, sets live flags,
and submits the packed output. Native cases test both saved words and complete
file preservation around them. Actual attenuation/calibration remains a hardware
question. [Original setter][volume-setter]

**`0xB50` is a u32 percentage**, default 100. `9D99C` reads runtime maximum
`owner+B78` and runtime enable byte `owner+BF3`, both outside the payload. With
enable zero it returns the maximum directly. Otherwise its exact arithmetic is:

```text
((max(10, saved_percentage) * runtime_maximum) modulo 2^32) // 100
```

It does not rewrite the saved value. The two independently injected ceilings
216 and 256 exercise both known scales; no marketing-model or legal-region
assignment is inferred here. Values above 100 are accepted by the raw setter,
and overflow is observable; they are not qualified UI choices. Complete slider
bounds, key handling and provider precedence require the lock model below.

## Volume lock lives in separate files

Original path constructors `22D0F0/22D278` produce
`iPod_Control/Device/_volumelocked` and `_volumeunlocked`. The loader `22D2C8`
prefers the locked path when both exist, reads a 32-byte record into global
`108823D4`, transforms it, calls provider `193498`, and reapplies its limit through
`193218` → Settings property `604F`. This makes the sidecar a separate authority
that can reassert a value after a raw Preferences edit. [Lock exports][lock-export]

| Plain offset | Size | Meaning |
| --- | ---: | --- |
| `0x00` | 4 | u32 limit value; `FFFFFFFF` is the provider's absent sentinel. |
| `0x04` | 1 | Lock flag; the getter interprets any nonzero byte as true. |
| `0x05` | 27 | Region containing the combination's ASCII string and retained suffix. |

For the sentinel, `193498` returns failure, forces the lock observation false and
returns the literal string **`0000`**. Otherwise it returns the stored string and
booleanized flag. The native record producer `193558` copies the limit, low byte
of the flag, and **the string including its terminating NUL**. Its helper
`2230D4` returns `strlen + 1`; treating that helper as ordinary `strlen` gives the
wrong interpretation. Bytes after the copied NUL remain unchanged. Four nonzero
suffix fixtures explicitly prove this behavior. The string region is not all
padding, and this pass does not qualify arbitrary string lengths as valid PINs.

`B41F8` and `B41B0` implement the same transform for each u32:

```text
encoded_word = plain_word XOR ~device_word XOR 0xA4253891
device_word  = memory[A0450() + 4]
```

Twelve native transform roundtrips per input cover four injected device words
and three whole-record patterns. The identity word's hardware origin is still
unqualified; it must not be labelled a serial number from this evidence alone.

Static workflow `22CF00` removes both existing sidecar paths, fills the provider
record, and, when locking is requested, writes 32 transformed bytes to the locked
path. The unlocked branch creates no new file. This is an observed firmware
workflow, not an iOpenPod implementation prescription: complete PIN validation,
failure handling, recovery and actual host-edit adoption still need research.
No lock-file writer or lock-bypass feature was added.

## Photo settings and coupled changes

`0xB3E` maps `0` to manual, `1/2/3/4/5` to **2/3/5/10/20 seconds**. All other
byte values map to zero in `16E964`; `16E85C` starts no automatic advance for a
zero result. The mapper is tested for all 256 stored values. [Photo export][photo-export]

Music `0xB3F`, u64 playlist ID `0xB40`, and runtime Photo UI `+7E` work together:

| Mode | Meaning and native behavior |
| --- | --- |
| 0 | From iPhoto, offered only when provider `+4C` equals **exactly 1**. |
| 1 | Off; after slideshow setup, the music-start path is skipped. |
| 2 | Selected nonzero persistent playlist ID. |
| 3 | A playlist whose ID is zero; the selected row is held in runtime `+7E`. |
| 4 | Now Playing; slideshow music setup returns immediately, retaining playback. |

The fixed labels are original strings `5045` From iPhoto, `6436` Now Playing and
`602F` Off, selected by `16EC18`. `16E668` stores zero ID for modes 0/1/3/4 and
the selected nonzero ID for mode 2. The last zero-ID playlist row stores runtime
`-1`; an earlier zero-ID row stores its actual row. Therefore mode 3 cannot be
reconstructed completely from Preferences alone.

Resolver `16D8B8` changes unavailable mode 0 or missing-playlist mode 2 to mode 1
while **retaining stale playlist-ID bytes**. Mode 3 uses its valid transient row
or falls back to the final row. Raw modes `5..255` return row 0 without rewriting
the preference; this is not qualification of those modes as sensible selections.
Slideshow start `16CED8`, not the getter alone, establishes the documented
Now Playing/Off behavior. [Photo consumer export][photo-consumer-export]

Transition getter `16E9C4` independently validates this mapping:

| Saved ID | Selection property | English menu label |
| --- | --- | --- |
| 1 / 2 / 3 | `5038/5039/503A` | Wipe across / Wipe down / Wipe from center |
| 6 | `503C` | Push across |
| 7 | `503B` | **Unresolved**: accepted by getter, absent from current menu and English strings. |
| 8 | `503E` | Push down |
| 9 / 10 | `503F/5040` | Cube across / Cube down |
| 11 / 12 / 13 / 14 | `5041..5044` | Page flip / Radial / Swirl / Dissolve |

Transition mode `0xB3B=0/1` selects Off/Random and ignores the specific ID. Any
other mode takes the specific-ID path. An invalid ID resets **both mode to 0
and ID to 255** through the compound save; a valid ID leaves even noncanonical
mode 255 intact. The 1,024 cases per input check every ID under modes 0/1/2/255.
Native acceptance of ID 7 is not enough to invent its visual effect.

## Radio region and actual channel grids

`0xB4E` stores `0` Americas, `1` Asia, `2` Australia, `3` Europe, `4` Japan.
Getter `242578` selects resource `581F + region`; `241328` cycles exactly five
UI choices, while `1928B8` stores any low byte. The frequency display divides
the word by ten into its decimal components, establishing 100 kHz units.
[Radio converter/configuration export][radio-export]

| Region | Frequency word | Channel indices | Grid represented in MHz |
| --- | --- | --- | --- |
| Americas | `875 + 2*n` | 0..102 | 87.5..107.9, step 0.2 |
| Asia | `875 + n` | 0..205 | 87.5..108.0, step 0.1 |
| Australia | `875 + 2*n` | 0..102 | 87.5..107.9, step 0.2 |
| Europe | `875 + n` | 0..205 | 87.5..108.0, step 0.1 |
| Japan | `760 + n` | 0..139 | 76.0..89.9, step 0.1 |

`241944` installs these bounds and chooses station-table IDs `0/10/3/1/2`.
`241D54` and `241E00/2424A4` convert the two directions. All 758 canonical
channels roundtrip per input. Americas additionally increments an even retained
frequency word to odd. Division truncates toward zero: 874 maps to channel zero
for Americas/Australia, so configuration can retain 874 in Australia rather than
clamping it to 875. These are code-defined grids and edge behavior, not RF
hardware measurements. Unknown region codes have no qualified grid; converters
return zero and configuration does not replace existing bounds with a valid one.

## Artwork cache and inherited decoder options

`0xB4C`, formerly unnamed property `60B8`, controls the artwork cache participant.
Setter `B2DC8` uses the full input for comparison/branching, then saves its low
byte. A nonzero input enables; zero disables. Injecting 256 can therefore enable
the service while saving zero. Ordinary UI values remain 0/1.

`1BFB94` sizes a shared resource pool and calls participant enable slots;
`1BFD18` calls disable slots and releases the pool. Sole direct registration
`CB984` → `1BFFC0` constructs `206D30`, participant ID 0, vtable `6732A4`.
`206C5C` → `205CFC` spawns `205DB4` with the original name **ArtworkLoadTask** at
`2AA7FC`. Preparation `205E64` requests artwork type 2 through `18D098/18D010`
and queues descriptors for two image-format requests, including filename,
offset/size and image metadata. Thus cache allocation/lifecycle is established;
turning off artwork visibility is not. [Participant][participant-export],
[worker][worker-export], [preparation][prepare-export]

The 774 native cases per input use synthetic iterator, pool and participant
boundaries to prove the setter's callback order and saved-byte behavior. They
do not simulate actual worker I/O or guarantee a performance effect.

Inherited bytes `0x8E2/0x8E3` pass through `ACA48/B3028` into decoder `F4E44`.
That six-instruction function ignores both arguments, checks only the decoder
object's first word, and returns `-4` for the matching header or `-50` otherwise.
Both header cases and all 256 complementary argument pairs preserve Preferences.
The current consumer's lack of effect is known; historical intended meanings
remain unknown, and the bytes are not labelled padding. [Decoder export][decoder-export]

## Week start, datetime and remaining questions

The previous inventory's `0xB20` citation to Settings **`60DB` was wrong for
Video**. Video's setter is **`60AA`**, computed from literal `192844=60A8` plus 2
in `1919D8`; it stores the low byte through `B40A8`. Getter `A0444` reads that
same byte. Label callback `19324C`, property **`600C`**, maps 0..6 to original
strings Sunday..Saturday. All 256 stores and seven labels are natively checked.
`60DB` is the English resource Last, First, not this preference's setter.

This closes the stored byte and label mapping, but the current Calendar renderer,
its malformed-value handling and the actual option-list binding remain open.
Do not import Mini's modulo behavior solely by analogy. This work does not
requalify the Video alarm projection as writable: `0xB22` remains a possibly
disabled/stale **Clock alarm snapshot**, with clock records in the separate
`iPod_Control/Device/clock` file as documented in the prior report. Calendar
loading/editing must remain available when datetime interpretations are uncertain.

The largest remaining questions are still substantial:

- Unmapped leading blobs, historical/indirect consumers and `0xB0A` meaning.
- Physical channel orientation, track gain curve, runtime maximum/provider and
  full Volume Limit/PIN state machine, including failure and recovery paths.
- Native transition ID 7 and exact effect renderers; transient music-row adoption.
- Current Calendar week-start renderer and malformed selector behavior.
- Complete current clock city/region domains, invalid pairs and adoption across
  the clock collection; this pass did not extend those domains.
- Remaining menu masks, setup/font/contrast fields and consumers already listed
  in the full-file inventory. Unknown data must stay byte-preserved.

The script, inventory builder and this report passed focused Ruff/Markdown
validation. No broad application tests were run because this pass changes only
offline evidence and research documentation.

[receipt]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-followup-20261107-final-v6/receipt.json
[inventory]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-fields-20261107-final-v3/field-inventory.json
[combined]: ../../../ipod-firmware-lab/artifacts/preferences-video-consolidated-20261107-final-v3/field-inventory.json
[artist]: ../../../ipod-firmware-lab/artifacts/preferences-video-alternate-text-20261107-final-v3/receipt.json
[artist-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-metadata-binding-20261107-export-v1
[volume-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-followup-export-20261107-v1
[volume-setter]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-followup-export-20261107-v1/00116d84.c
[lock-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-volume-lock-deep-export-20261107-v1
[photo-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-more-export-20261107-v1
[photo-consumer-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-more-export-20261107-v1/0016ced8.c
[radio-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-followup-export-20261107-v1
[participant-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-participant-export-20261107-v1
[worker-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-artwork-worker-export-20261107-v1
[prepare-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-artwork-prepare-export-20261107-v1
[decoder-export]: ../../../ipod-firmware-lab/artifacts/preferences-video-deep-more-export-20261107-v1/000f4e44.c
