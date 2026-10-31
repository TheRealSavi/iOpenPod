# Chapter artwork formats across firmware families

Research date: 2026-10-30. Nine firmware samples beyond the previous nano 5
investigation were checked directly. The comparison found missing Chapter format
declarations for Video, nano 3, and nano 4; **those verified sets are now adopted**.
All four inspected Classic releases match its existing F1055/F1029 set. Nano 5
remains the already adopted F1073 case. The initial inspection changed no product
capabilities; the later implementation and regression evidence are recorded below.
No physical device files were changed.

## Verified format matrix

Dimensions below are native raster width by height; row bytes describe the native
stride. A Chapter declaration is taken from the firmware's `ChapterImageSpecs`
branch, rather than inferred from its ordinary cover list or every format its
raster factory recognizes.

| Firmware samples | Declared Chapter formats | Catalog before this adoption |
| --- | --- | --- |
| Video families 13/20/25, RetailOS 1.3 | F1028: 100 × 100, row 200; F1029: 200 × 200, row 400 | Missing Chapter support and formats; both layouts already exist as covers |
| Nano 3, family 26, RetailOS 1.1.3 | F1055: 128 × 128, row 256; F1029: 200 × 200, row 400 | Missing Chapter support and formats; ordinary covers include F1055 but omit F1029 |
| Nano 4, family 31, RetailOS 1.0.4 | F1071: 240 × 240, row 480 | Chapter support is true, but Chapter formats are empty; F1071 already exists as a cover |
| Classic family 24 / 1.1.2, 33 / 2.0.1, 35 / 2.0.4, 38 / 2.0.5 | F1055: 128 × 128, row 256; F1029: 200 × 200, row 400 | Matches all current Classic profiles |
| Nano 5, family 34, RetailOS 1.0.2; previous investigation | F1073: 240 × 240, row 480 | Matches the recently corrected Chapter capability; shared with covers |

Sources: [Video native receipt][video], [nano 3/4 native receipt][nano34],
[Classic native receipt][classic], and the existing
[nano 5 contract](nano5-chapter-artwork-contract.md). The comparison uses the
[catalog snapshot][catalog-snapshot] taken from the product's
[Device Registry](../../src/device_registry/data/catalog.py) after the nano 5 fix.
The [adopted catalog snapshot][adopted-catalog] records the completed correction.

All checked Chapter descriptors have 16 bits per pixel and native raster tag
`0x565`. Native Video and nano 3/4 converters additionally map that tag to
`0x4c353635`, FourCC `L565`, and distinguish the big-endian `B565` case.
Their layouts agree with the existing RGB565 LE definitions. This does not
establish every renderer or visible rectangle policy. [Video receipt][video],
[nano receipt][nano34], [Classic descriptor words][classic].

## Primary entry points and execution

| Sample | Capability emitter | Raster descriptor routine | Primary exports |
| --- | --- | --- | --- |
| Video 13/20/25 | `00175c74`; Chapter branch `00176718` | `00135038` | [emitter and fields][video-emitter] |
| Nano 3 | `0813e8e8` | `080ec668` | [emitter][nano3-emitter] |
| Nano 4 | `0812b968` | `080f1158` | [emitter][nano4-emitter] |
| Classic 24 | `081289ec` | `080dfc54` | [emitter][classic24-emitter] |
| Classic 33 | `0812ddc8` | `080e3b64` | [emitter][classic33-emitter] |
| Classic 35 | `081453d8` | `080fac80` | [emitter][classic35-emitter] |
| Classic 38 | `08145938` | `080fad38` | [emitter][classic38-emitter] |
| Nano 5; previous investigation | `08007120` | `0819435c` | [existing report](nano5-chapter-artwork-contract.md) |

These are runtime addresses under each image's independent startup-derived map.
Video code uses logical base zero. The Classic and nano code maps raw DRAM to
`0x08000000`; each source offset and initialized region differs. Every new probe
checks its exact source hash and loads that image's own map. The scripts and
receipts identify the mappings and native adapters. No physical iPod is involved.

The new investigation passes **27 bounded native cases**:

- Classic: eight descriptor calls, two per release, without call adapters. The
  complete capability emitter and dictionary helper for each release were also
  exported and checked statically for the Chapter-specific literals and arguments.
- Video: twelve cases across three independently loaded images: two descriptors
  and full capability emission with support disabled and enabled per image. Native
  startup, pixel conversion, and per-format field emission execute firmware bytes;
  XML output and short string-formatting helpers have documented Host adapters.
- Nano 3/4: three descriptor cases, including native pixel conversion checks, and
  four disabled/enabled Chapter emitter-segment cases. The native segment branches
  and descriptor calls execute unchanged; preceding register setup and XML/string
  handling have explicit adapters. Nano 4's inline Thumb switch and ARM helper
  execute natively despite incomplete linear decompilation.

These cases confirm declarations and geometry. They do not execute a complete
player, prove physical Chapter image delivery, or independently verify every
Chapter-header flag gate on these other releases. Video's earlier
[timing experiment](ithmb/artwork-timing-experiments.md) separately demonstrated
timed F1028/F1029 changes in its emulator, including without MHOD 17.

## Other emitted fields

| Samples | AssociatedFormat | ExcludedFormats in the Chapter dictionary | BackColor |
| --- | --- | --- | --- |
| Video 13/20/25 | Not emitted by this writer | Not emitted by this writer | `FFFFFFFF` |
| Nano 3 | 0 | Not emitted | `FFFFFFFF` |
| Nano 4 | 0 | Not emitted | `00000000` |
| Classic 24/33/35/38 | 0 for each representation | Not emitted | `FFFFFFFF` |

The checked entries are non-interlaced, use aligned rows, and omit rotation.
Classic 35/38's dictionary helper supports `ExcludedFormats`, but both Chapter
calls pass zero so the key is absent. The nearby `FFFFFFFF` string is BackColor;
it is not an all-media exclusion mask. Absence of an exclusion field does not
prove unrestricted codec or player-view eligibility. Sources: each
[Classic helper export][classic-artifacts], [Video properties][video], and
[nano emitter arguments][nano34].

## Exact source images and limits

| Sample | Bytes inspected | SHA-256 |
| --- | --- | --- |
| Classic 24, 1.1.2 | 9,924,476 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` |
| Classic 33, prepared 2.0.1 | 10,513,984 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| Classic 35, 2.0.4 | 10,597,864 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` |
| Classic 38, 2.0.5 | 10,632,448 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |
| Nano 3, 1.1.3 | 10,790,256 | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` |
| Nano 4, 1.0.4 | 5,763,080 | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` |
| Nano 5, 1.0.2 | 7,284,288 | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` |
| Video 13, 1.3 | 7,559,680 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| Video 20, 1.3 | 7,559,680 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| Video 25, 1.3 | 7,561,216 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` |

The [independent inventory][images] checks these exact local paths and hashes.
Classic 33's prepared image is distinct from its retained logical raw body
(`b3dc475bb3be11be8dc8fdc3d4b86d8c5adbaa3afc79c2e1f222205a5e0792cb`);
the probe verifies that distinction rather than silently replacing one with the
other. Video 13 and 20 are byte-identical; Video 25 adds 1,536 zero bytes. All
three full extracted images were loaded independently. [Classic receipt][classic],
[Video receipt][video].

Nano 4's supplied plaintext has an uncertain final eight bytes at raw
`0x57f000..0x57f007`, runtime `0x08570800..0x08570807`. Its probe guards both code
and memory reads against that range, including overlapping reads. No reported
case touches it. The results do not certify those eight bytes or an entirely
authenticated nano 4 plaintext image. [Guarded native receipt][nano34].

No usable nano 1/2/6/7 firmware was found in the lab, the supplied Downloads IPSW
collection, emulator workspaces, or the normal local iTunes firmware-cache paths.
Those generations remain **unverified in this pass**. The same applies to older
full-size/color iPods and Minis without inspected images. Empty catalog fields or
missing historical producer tables do not establish absence of firmware support.

## Product implications and reproduction

Device Registry now supplies the Video pair F1028/F1029, nano 3 pair F1055/F1029,
and nano 4 format F1071 with the Chapter artwork role under
[ADR-0139](../adr/0139-complete-timed-artwork-formats-and-counts.md). Shared cover
layouts stay shared; nano 3 additionally receives the F1029 representation during
explicit timeline preparation. The existing flag coordinator only runs when
Chapter formats are present, so the old support boolean alone on nano 4 was
insufficient. No lower-level format inference or new runtime dependency is added.

The save/reload regression now covers Video 5 and 5.5 and nano 3/4/5, each with an
explicit timeline and an ordinary cover, with and without unknown header bits.
It checks flags, original Chapter positions, each native Chapter raster's actual
pixels, and byte-identical shared image files against the prior cover-only
target. Ordinary covers preserve their existing header flags. Nano 5 additionally
checks the complete saved Extras blob against the CDB representation. A retained
nano 3 timeline test verifies that reapplying references adds only F1029 while
leaving old image shards unchanged. Sources: [save regressions][save-tests] and
[catalog regressions][catalog-tests]. Existing affected timelines require an
explicit artwork save; unrelated metadata edits do not broadly repair them.

### Chapter flags checked before adoption

Native parser and importer probes independently verify the serialized masks on
each newly adopted firmware family:

| Samples | Header mask 1 | Header mask 2 import effect |
| --- | --- | --- |
| Video 13/20/25, 1.3 | Enables named Chapter index | Adds native Track `+0x1c` mask `0x40` |
| Nano 3, 1.1.3 | Enables named Chapter index | Adds native Track `+0x1c` mask `0x840` |
| Nano 4, 1.0.4 | Enables named Chapter index | Adds native Track `+0x1c` mask `0x840` |

The actual saved synthetic Chapter body was parsed with native atom search and
big-endian conversion. Flags 0/1/2/3 and `0x80000001`/`0x80000003` preserve the
raw unknown high bit and produce the expected named counts and starts. Native
importer slices call the actual flag accessor and retain preexisting Track bits.
The three Video images pass 18 cases; nano 3/4 pass 12. Allocation, container
ownership and the exact importer-slice entry state have explicit Host adapters.
Sources: [Video flag receipt][video-flags] and [nano flag receipt][nano-flags].

Video's `0x40` is ordinary artwork presence, also set by MHIT's artwork byte. It
is not evidence for Classic's separate `0x800` Chapter-provider bit. The nano
checks likewise do not trace every downstream provider/cache route. The writer
enables only the two known serialized header masks; it never stores internal
firmware masks or selectors in the database. Full physical display acceptance
remains unverified.

### Commands

From the sibling `ipod-firmware-lab`, using the pinned images:

```powershell
uv run scripts/classic_chapter_formats.py
uv run scripts/video_chapter_formats.py
uv run scripts/nano34_chapter_formats.py
uv run scripts/video_chapter_flags.py
uv run scripts/nano34_chapter_flags.py
uv run --project ../iOpenPod python scripts/chapter_formats_inventory.py --output artifacts/chapter-formats-inventory-after-adoption
```

Probe sources: [Classic][classic-script], [Video][video-script],
[nano 3/4][nano-script], and [inventory][inventory-script]. The inventory requires
existing receipts to match; a changed catalog needs a new output directory to
preserve this comparison. Firmware, Ghidra projects, and generated binary
artifacts stay in the private lab and never become application dependencies.

From this repository, run the portable regressions with:

```powershell
uv run pytest tests/device_registry/test_artwork_profiles.py tests/iOpenPod/app/services/test_chapter_artwork_save.py
```

[classic]: ../../../ipod-firmware-lab/artifacts/chapter-formats-classic/native-descriptors.json
[video]: ../../../ipod-firmware-lab/artifacts/chapter-formats-video/native-capability-probes.json
[nano34]: ../../../ipod-firmware-lab/artifacts/chapter-formats-nano34/native-probes.json
[catalog-snapshot]: ../../../ipod-firmware-lab/artifacts/chapter-formats-inventory/catalog.json
[adopted-catalog]: ../../../ipod-firmware-lab/artifacts/chapter-formats-inventory-after-adoption/catalog.json
[images]: ../../../ipod-firmware-lab/artifacts/chapter-formats-inventory/images.json
[video-emitter]: ../../../ipod-firmware-lab/artifacts/chapter-formats-video/13-seeds/00175c74.c
[nano3-emitter]: ../../../ipod-firmware-lab/artifacts/chapter-formats-nano34/nano3-seeds/0813e8e8.c
[nano4-emitter]: ../../../ipod-firmware-lab/artifacts/chapter-formats-nano34/nano4-seeds/0812b968.c
[classic24-emitter]: ../../../ipod-firmware-lab/artifacts/chapter-formats-classic/classic24-emitter.c
[classic33-emitter]: ../../../ipod-firmware-lab/artifacts/chapter-formats-classic/classic33-emitter.c
[classic35-emitter]: ../../../ipod-firmware-lab/artifacts/chapter-formats-classic/classic35-emitter.c
[classic38-emitter]: ../../../ipod-firmware-lab/artifacts/chapter-formats-classic/classic38-emitter.c
[classic-artifacts]: ../../../ipod-firmware-lab/artifacts/chapter-formats-classic/
[classic-script]: ../../../ipod-firmware-lab/scripts/classic_chapter_formats.py
[video-script]: ../../../ipod-firmware-lab/scripts/video_chapter_formats.py
[nano-script]: ../../../ipod-firmware-lab/scripts/nano34_chapter_formats.py
[inventory-script]: ../../../ipod-firmware-lab/scripts/chapter_formats_inventory.py
[video-flags]: ../../../ipod-firmware-lab/artifacts/chapter-flags-video/native-chapter-flag-probes.json
[nano-flags]: ../../../ipod-firmware-lab/artifacts/chapter-flags-nano34/native-probes.json
[save-tests]: ../../tests/iOpenPod/app/services/test_chapter_artwork_save.py
[catalog-tests]: ../../tests/device_registry/test_artwork_profiles.py
