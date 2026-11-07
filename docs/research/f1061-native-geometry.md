# F1061 native geometry across iPod generations

Research date: 2026-10-31. This supplements the
[Classic 7G issue 178 comparison](classic7-artwork-firmware-178.md) with independent
checks of Video 5/5.5, Classic 6/6.5, and nano 3 firmware. It establishes native
format geometry and advertised purpose, not a completed physical display test.

## Finding

**There is no evidenced F1061 geometry split between Classic 6, 6.5 and 7.**
Their inspected latest local firmware, and nano 3's, all return **55 by 55 pixels,
112 bytes per row, 16-bit RGB565** from the native F1061 descriptor function.
The native raster therefore occupies **6160 bytes**: 55 rows of 110 pixel bytes
plus two alignment bytes per row. The extra alignment sample is not a 56th pixel.

**iPod Video 5 and 5.5 do not advertise F1061 for album art.** All three inspected
Video updater families advertise F1028 (100 by 100) and F1029 (200 by 200).
That is a format-set distinction, not a model-specific F1061 variant. Do not add
F1061 to their cover profiles as part of this correction.

## Native verification matrix

| Device family | Updater | RetailOS | Native descriptor | Advertised cover evidence | Result |
| --- | --- | --- | --- | --- | --- |
| Video 5/5.5 package family | 13 | 1.3 | `00135038` | Native `00175c74` emitter | F1028 100x100, F1029 200x200; no F1061 |
| Video 5/5.5 package family | 20 | 1.3 | `00135038` | Native `00175c74` emitter | Same |
| Video 5/5.5 package family | 25 | 1.3 | `00135038` | Native `00175c74` emitter | Same |
| Classic 6 | 24 | 1.1.2 | `080dfc54` | `081289ec` emitter | F1061 55x55, stride 112 |
| Classic 6.5 / 120GB | 33 | 2.0.1 | `080e3b64` | `0812ddc8` emitter | F1061 55x55, stride 112 |
| Classic 7 | 35 | 2.0.4 | `080fac80` | `081453d8` emitter | F1061 55x55, stride 112 |
| Classic 7, later updater | 38 | 2.0.5 | `080fad38` | `08145938` emitter | F1061 55x55, stride 112 |
| nano 3 | 26 | 1.1.3 | `080ec668` | `0813e8e8` emitter | F1061 55x55, stride 112 |

These are the latest builds preserved in the local per-family workspaces.
The native probe independently executes all five F1061 descriptors and the six
Video F1028/F1029 descriptors. It also executes each Video's AlbumArt capability
branch with XML output/formatting services adapted to capture properties. The
latter establishes what these Video firmwares advertise; a descriptor factory's
recognition alone would not establish a supported cover format.
[Probe source](../../../ipod-firmware-lab/artifacts/f1061_geometry_probe.py),
[all native results](../../../ipod-firmware-lab/artifacts/f1061-native-geometry/native-probes.json).

Classic 24 and nano 3 receive new read-only Ghidra exports. Before export, every
initialized program region is compared to the hash-verified image. The capability
branches load base format 1055 and advertise offsets 0, 13, 5 and 6: F1055,
F1068, F1060 and F1061. F1061's output dimensions come from the same descriptor
executed by the probe; it is not only a recognized unused format.
[Classic 24 emitter](../../../ipod-firmware-lab/artifacts/f1061-native-geometry/Classic24/081289ec.c),
[Classic 24 receipt](../../../ipod-firmware-lab/artifacts/f1061-native-geometry/Classic24/receipt.json),
[nano 3 emitter](../../../ipod-firmware-lab/artifacts/f1061-native-geometry/Nano3/0813e8e8.c),
[nano 3 receipt](../../../ipod-firmware-lab/artifacts/f1061-native-geometry/Nano3/receipt.json).

The Classic 33 emitter was previously byte-checked and advertises the same four
AlbumArt representations. Its F1061 descriptor was executed again in this pass.
The independent Classic 35/38 exports and advertisement traces are in the prior
issue-178 report.
[Classic 33 emitter ARM](../../../ipod-firmware-lab/artifacts/itunesdb201-artwork-geometry-key-consumers/0812ddc8-FUN_0812ddc8.asm.txt),
[Classic 33 recognized-versus-advertised catalog](../../../ipod-firmware-lab/notes/itunesdb/artwork-raster-format-catalog.md),
[Classic 35/38 comparison](classic7-artwork-firmware-178.md).

## Exact input identities and memory maps

| Updater | Source member | OSOS SHA-256 |
| --- | --- | --- |
| 13 | `Firmware-13.6.3` | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| 20 | `Firmware-20.6.3` | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| 25 | `Firmware-25.6.3` | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` |
| 24 | `Firmware-24.9.1.2` | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` |
| 33 | `Firmware-33.9.0.1`, normalized analysis input | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| 35 | `Firmware-35.9.0.4` | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` |
| 38 | `Firmware-38.9.0.5` | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |
| 26 | `Firmware-26.9.1.3` | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` |

Video code uses logical base zero and native startup `00083848` establishes its
runtime data copies and BSS. Family 13 and 20 executable images are identical;
family 25 has the same prefix followed by 1536 zero bytes. This is byte identity
for these inspected packages, not an assumption that arbitrary firmware versions
share function addresses.
[Video acquisition and mapping](../../../ipod-firmware-lab/notes/games/video-family-independent-verification.md),
[Video native capability receipt](../../../ipod-firmware-lab/artifacts/chapter-formats-video/native-capability-probes.json).

Classic and nano 3 use DRAM at `08000000` and IRAM at `22000000`, with source
ranges taken from each image's startup-derived map. Classic 33 uses its normalized
analysis input and preserved region manifest; its independently decrypted logical
OSOS hash is `b3dc475bb3be11be8dc8fdc3d4b86d8c5adbaa3afc79c2e1f222205a5e0792cb`.
The normalization distinction must not be mistaken for different firmware.
[Classic 24 map](../../../ipod-firmware-lab/Classic24FW/evidence/runtime-map.json),
[Classic 33 manifest](../../../ipod-firmware-lab/Classic33FW/ghidra/stock-2.0.1/classic201.manifest.json),
[nano 3 map](../../../ipod-firmware-lab/Nano3FW/evidence/runtime-map.json).

## Implications for authoring and automatic repair

The evidence supports a common F1061 **visible** authoring geometry of 55 by 55
for Classic 6/6.5/7 and nano 3. Fresh tightly allocated canonical data needs 6160
bytes, with explicit 112-byte row stride. This does not require a new model split.
Video 5/5.5 F1028/F1029 behavior should remain unchanged.

Preserved allocation and visible geometry must remain distinct. A retained
6272-byte slot supplies 56 aligned rows; the extra row does not change the native
F1061 descriptor. The prior 7G native bitmap probes accepted current-produced
6272-byte slices and constructed 55-by-55 bitmap headers. Conversely, 6050 bytes
is only a tightly packed 55-by-55 RGB565 buffer and cannot supply 55 native
112-byte rows. Its missing stride bytes need re-encoding, not a metadata-only
size correction.
[7G native bitmap evidence](classic7-artwork-firmware-178.md#raster-geometry-and-advertised-associations).

Changing a catalog number alone cannot restore existing incorrectly sampled
content. If historical output scaled an image to 56 columns, its first 55 columns
represent a crop of that scaling. Repair should distinguish newly encoded pixels
from a retained allocation and use a suitable captured source representation when
resampling is needed. Merely relabeling an existing 56-wide payload as 55-wide does
not reverse the old scaling. Correctly authored 55-wide data can coexist with a
larger retained allocation if metadata and verification preserve that distinction.

The implementation decision is recorded in
[ADR-0218](../adr/0218-author-and-repair-native-f1061-geometry.md). Automatic repair
uses the normal analyze, prepare, independently verify and Storage publication
workflow. It preserves existing shard bytes and resamples into fresh files when
needed. Shared images, timed entries, retained byte extents and unavailable source
artwork remain explicit constraints; this finding does not justify blanket
truncation or normalization of unknown content.

## Validation limits and reproduction

Run from the iOpenPod repository:

```text
uv run ../ipod-firmware-lab/artifacts/f1061_geometry_probe.py
```

The new run passed five F1061 calls, six Video F1028/F1029 calls, and three native
Video AlbumArt emission cases. Functions execute as unmodified ARM instructions
in Unicorn 2.1.4. The Video harness provides startup memory aliases and adapted
XML/string output services; the descriptor calls require no display subsystem.
No physical device was accessed and no firmware or Ghidra project was changed.

This settles the inspected formats' descriptor geometry and advertised use. It
does not establish physical display acceptance of a new repair, every renderer's
clipping behavior, or that this difference caused issue 178's all-artwork failure.

## Corrected producer fixture

A second, separately preserved fixture was generated through the current iOpenPod
producer after its F1061 authoring geometry changed to 55 by 55. Its ArtworkDB
SHA-256 is `491b80531d02f22cf7da676b819cca977ed692aa27eeb2eacb2526428bbed17d`.
It contains four F1061 representations with 6160-byte pixel lengths, 112-byte row
stride, and 55-by-55 visible bounds. The original issue-178 fixture and probe
results remain separate.

A copy of the earlier bounded native probe passed **32 bitmap reads** across the
two 7G firmware builds, including all eight canonical F1061 reads, together with
eight descriptor calls and twelve root-gate cases. Both native bitmap loaders
published 55-by-55 headers, retained the 6160-byte payload lengths and reproduced
the source pixel hashes. F1060's two-shard reads also remained valid.
[Copied probe](../../../ipod-firmware-lab/artifacts/f1061-native-geometry/native_probe_canonical.py),
[results and fixture identity](../../../ipod-firmware-lab/artifacts/f1061-native-geometry/native-canonical6160.json).

The same limits apply: filename resolution, allocation and filesystem services
are adapters; bitmap metadata is projected from the producer receipt. Root tests
skip image/album dataset bodies. The synthetic iTunesDB is unsigned. These results
validate the corrected producer's referenced raster slices against the native
reader and descriptor functions, not complete device import or physical display.
Reproduce with:

```text
uv run ../ipod-firmware-lab/artifacts/f1061-native-geometry/native_probe_canonical.py
```
