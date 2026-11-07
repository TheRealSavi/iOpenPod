# Classic 7G artwork: issue 178 firmware comparison

Research date: 2026-10-31. Scope: updater family 35 RetailOS 2.0.4 and updater
family 38 RetailOS 2.0.5, independently decrypted and analyzed. This investigation
compares the current producer with firmware behavior; it does not reproduce the
reporter's physical failure or establish that the issue is resolved.

This report preserves the pre-correction producer evidence. The subsequent
[cross-model verification](f1061-native-geometry.md) establishes the common native
F1061 geometry; [ADR-0218](../adr/0218-author-and-repair-native-f1061-geometry.md)
adopts 55-by-55 authoring and verified automatic repair. References below to the
current producer's 56-pixel default describe the investigated baseline.

## Result

The inspected artwork contracts agree across both updater families. Neither the
root importer nor the ordinary bitmap reader establishes a prohibition on multiple
`.ithmb` files for one format, a 32/256/500 MiB rollover boundary, a requirement for
MHFD value 6 instead of 2, or a requirement for the opaque preserved header words
to be nonzero. Current-produced raster slices, including both F1060 shards and
6272-byte F1061 allocations, were accepted by bounded executions of each firmware's
ordinary bitmap loader. This narrows the investigation; it is not complete native
ArtworkDB import, cache, operating-system or physical display acceptance.

Two distinctions remain relevant to authoring: F1061's native descriptor is
55 by 55 with 112-byte rows, and F1068 is advertised with `AssociatedFormat=2`,
where the three ordinary cover representations use zero. The former separates
visible geometry from stored allocation; the latter supports media-specific
format selection, rather than declaring F1068 unsupported. Neither finding alone
explains all artwork disappearing. Evidence and limits follow below.

The current producer also addresses the reported preparation refusal for retained
6,160-byte F1061 images; the focused regression selection passes 103 tests. This
supports treating that specific failure as addressed, while keeping the overall
physical blank-art report unconfirmed rather than closing it from silence.

## Exact inputs and reproducibility

| Updater | RetailOS | IPSW member | Logical OSOS SHA-256 |
| --- | --- | --- | --- |
| 35 | 2.0.4 | `Firmware-35.9.0.4` | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` |
| 38 | 2.0.5 | `Firmware-38.9.0.5` | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |

These are the latest releases preserved for the two 7G updater families in the
local lab. Package metadata independently supplies updater and release identities:
[35 extraction](../../../ipod-firmware-lab/Classic35FW/evidence/extraction.json),
[38 extraction](../../../ipod-firmware-lab/Classic38FW/evidence/extraction.json).
The issue's reported `1.62` is insufficient to identify either RetailOS build;
transport revision and RetailOS release are distinct evidence (ADR-0175).

Startup-derived mappings place initialized DRAM at `0x08000000`, from logical raw
file offset `0xaed8` for family 35 and `0xaf98` for family 38. IRAM begins at
`0x22000000`, raw offset zero. Full maps include initialized data and BSS:
[35 map](../../../ipod-firmware-lab/Classic35FW/evidence/runtime-map.json),
[38 map](../../../ipod-firmware-lab/Classic38FW/evidence/runtime-map.json).

A new read-only Ghidra export compared **all initialized memory regions** against
the hash-verified images before exporting 19 functions per family. Receipts record
function entries and complete instruction/body byte counts. No saved project,
firmware original or physical iPod was changed:
[exporter](../../../ipod-firmware-lab/artifacts/issue178-classic7/Issue178Export.java),
[35 receipt](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/receipt.json),
[38 receipt](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/receipt.json).
Names and C output remain analyst/decompiler interpretations, not Apple source.

The bounded native checks run with:

```text
uv run ../ipod-firmware-lab/artifacts/issue178-classic7/native_probe.py
```

Result: **8 descriptor calls, 32 bitmap loads, 12 root-gate cases passed**.
[Probe source](../../../ipod-firmware-lab/artifacts/issue178-classic7/native_probe.py),
[machine-readable results](../../../ipod-firmware-lab/artifacts/issue178-classic7/native-probes.json).
The probe pins Unicorn 2.1.4 and verifies each firmware hash before execution.

## Root import and whole-library failure

| Operation | Family 35 | Family 38 |
| --- | --- | --- |
| Main Artwork-directory loader | `0804d358` | `0804d384` |
| MHFD/MHSD root importer | `08058fc4` | `08059000` |
| MHLI/MHII image importer | `08074d1c` | `08074db8` |
| MHOD child dispatcher | `0808b4d8` | `0808b578` |
| MHNI thumbnail importer | `08093e18` | `08093ecc` |

Both main loaders discard a failed provisional Artwork library rather than
publishing it. Consequently malformed records, failed allocation or file access
can produce a whole-library absence; correctly decoding individual pixel slices
on the Host does not establish successful firmware import.
[35 loader](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/0804d358.c),
[38 loader](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/0804d384.c).

Both root importers read the 132-byte MHFD prefix and require its total length to
match the actual file length, whose high 32 bits must be zero. MHFD `+0x0c` must
be zero and the dataset count at `+0x14` must be nonzero. The word at `+0x10`
is not compared against 2 or 6. Its low halfword can be returned through an
optional output pointer. The opaque ranges `+0x20..+0x2f` and `+0x3c..+0x43`
do not supply acceptance gates in these routines.
[35 root ARM](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/08058fc4.asm),
[38 root ARM](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/08059000.asm).

Native root probes accept the actual current producer's MHFD6, its value-2
variant, and the variant zeroing those opaque words. Negative controls reject
nonzero `+0x0c` and zero datasets with `-208`, and a wrong total length with `-39`.
**These exercise the root gates and dataset dispatch only:** file services are
adapted, and type-1/type-2 dataset bodies are skipped by adapters. They do not
prove complete import of the fixture's image/album records.

Dataset type 1 invokes the image importer, type 2 invokes the album importer,
and other types skip their declared payload. Thus the conventional type-3
MHLF/MHIF dataset is skipped by this main reader. MHIF nominal image size cannot
explain rejection on this path, although Host consistency checks and other
producers/readers may still require it. MHOD type 2 enters thumbnail import;
other metadata children, including type-6 filler, are skipped according to their
own lengths. These results agree in both builds.
[35 children](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/0808b4d8.c),
[38 children](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/0808b578.c).

## Filenames, sharding and ordinary pixel reads

| Operation | Family 35 | Family 38 |
| --- | --- | --- |
| Filename token/path bridge | `080474e4` | `08047504` |
| Colon-separated path resolver | `08051a4c` | `08051a74` |
| Select thumbnail string cache | `080475ac` | `080475cc` |
| Allocate per-format string cache | `08053114` | `0805313c` |
| Insert/deduplicate cached bytes | `080babbc` | `080bac60` |
| Retrieve cached token | `080cbebc` | `080cbf60` |
| Ordinary bitmap loader | `080f32ec` | `080f33a4` |

MHNI's format ID, offset, length and filename token are independent fields. A
leading colon selects the Artwork base directory; the generic resolver replaces
colon separators with backslashes. Neither traced routine parses a format ID or
shard ordinal from `F1060_2.ithmb`.
[35 path bridge](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/080474e4.c),
[38 path bridge](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/08047504.c).

The per-format cache is a store of **multiple filename strings**, not a single
filename slot. Insertion compares string length and full bytes before reuse;
distinct strings get distinct token entries. Capacity grows by allocation.
Retrieval selects the thumbnail's own token. The visible growth thresholds govern
allocation increments, not an established maximum shard count. No fixed
same-format shard-count ceiling was found in these routines.
[35 insertion](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/080babbc.c),
[38 insertion](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/080bac60.c),
[35 retrieval](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/080cbebc.c),
[38 retrieval](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/080cbf60.c).

Each ordinary bitmap load resolves its filename, allocates MHNI length plus
alignment/header space, opens the selected file, seeks to MHNI offset, reads MHNI
length, closes the handle, and constructs the native bitmap header from the
format descriptor. Its optional allocator changed relative to the older 2.0.1
implementation; the two 7G builds agree. The load does not consult MHIF or compare
against 32/256/500 MiB. The routine does not test seek/read status or transferred
length before publishing the bitmap. A missing/truncated file remains a plausible
failure, even if the metadata is internally consistent.
[35 bitmap ARM](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/080f32ec.asm),
[38 bitmap ARM](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/080f33a4.asm).

The current producer fixture contains four images, each with four formats; F1060
rolls over after two images using an artificial 409600-byte cap. Native bitmap
calls in both builds read all 16 referenced slices, including both offsets in
`F1060_2.ithmb`, and publish the expected headers and identical pixel hashes.
**Filename resolution, allocation and filesystem services are adapters in this
probe; the native bitmap's offset/length/read sequencing and descriptor wrapper
execute unmodified.** The filename-cache conclusion comes from separate static
analysis, not this fixture execution. This is neither a many-shard stress test
nor a proof that every complete device Sync succeeds.

Both SysInfo emitters advertise `MaxThumbFileSize=50` and `MaxFileSizeInGB=4`.
The former's unit and enforcement are not established here; it must not be
silently interpreted as 50 MiB or used to prescribe a new rollover cap.
[35 emitter](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/081453d8.c),
[38 emitter](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/08145938.c).

## Raster geometry and advertised associations

Native descriptor functions `080fac80` / `080fad38` produce the following in both
builds. Each row was executed independently; all use 16-bit RGB565 tag `0x565`.

| Format | Width | Height | Row bytes | Descriptor-sized payload | AssociatedFormat |
| --- | --- | --- | --- | --- | --- |
| F1055 | 128 | 128 | 256 | 32768 | 0 |
| F1060 | 320 | 320 | 640 | 204800 | 0 |
| F1061 | 55 | 55 | 112 | 6160 | 0 |
| F1068 | 128 | 128 | 256 | 32768 | 2 |

The emitters also advertise F1069 with association `0x20000` and excluded formats
`-1`. Association values are traced through parameter 15 of the format-property
emitter (`08144a4c` / `08144fa0`) to the literal `AssociatedFormat` property.
This establishes what firmware advertises. It does not by itself prove a media
kind dispatch rule or rejection of an extra F1068 thumbnail on an audio Track.
The importer admits thumbnail representations without that association test.
[35 descriptor](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/080fac80.c),
[38 descriptor](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/080fad38.c),
[35 format properties](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/08144a4c.c),
[38 format properties](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/08144fa0.c).

F1061's descriptor and bitmap header remain 55 by 55 even when the declared read
length is 6272 and the producer's MHNI bounds are 56 by 56. All four such current
fixture allocations loaded in each firmware. Therefore a 6272-byte allocation
is not inherently rejected by this reader. Tight 6050-byte RGB565 lacks the
112-byte stride's required 6160 bytes. Resampling content into 56 columns rather
than the native 55 is a separate visual-fidelity concern: it does not establish
blank artwork. This pass does not trace every 7G renderer or claim a physical
crop result. The earlier 2.0.1 generic widget's 55-by-55 clipping result remains
separately scoped in the [older evidence](classic201-artwork-semantics-2026-10-28.md).

## Identity and other suspected fields

The direct Track-to-image lookup remains authoritative when nonzero; failure does
not switch to reverse Track-ID lookup. The corresponding native Track field is
`+0xf0` in these builds. With zero direct reference, the reverse lookup uses the
Track's 64-bit identity at native `+0x110/+0x114`.
[35 lookup](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/080457e4.c),
[38 lookup](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/080457d8.c).

The image importer's copied MHII fields and the bitmap reader do not use source
image byte size to determine raster dimensions or pixel read length. Thus the
reported compressed-source-size versus decoded-RGB-size difference is not an
established mechanism for rejecting these thumbnail slices. This does not resolve
all source-size semantics or prove no other firmware consumer reads the field.
[35 image importer](../../../ipod-firmware-lab/artifacts/issue178-classic7/35-verified/08074d1c.c),
[38 image importer](../../../ipod-firmware-lab/artifacts/issue178-classic7/38-verified/08074db8.c).

## Issue history and current producer comparison

Reviewed 2026-10-31 against iOpenPod commit
`2f4e9a8b7ac514357c58d6137f210332584aaf70` (project version 2.1.0).
Existing uncommitted Phase-related work was left untouched; the artwork source
files reviewed here match that commit. This investigation changes no product code.

[Issue 178](https://github.com/TheRealSavi/iOpenPod/issues/178) starts with
v1.67.0/v1.68.1 and an MC293. Later comments include another Classic 7G MC297 and
separate Classic 6G observations. The reported `1.62` does not identify either
RetailOS image in this report: the project has independently observed FireWire
revision 1.62 alongside RetailOS 2.0.1. See
[ADR-0175](../adr/0175-model-native-genius-capabilities-by-firmware.md).

The thread contains useful observations but changing hypotheses. A
[later iTunes comparison](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-6113260630)
reports working `_N` shards and a concrete iOpenPod preparation refusal involving
6,160 versus 6,272-byte F1061 images. That is stronger evidence than the earlier
inference that sharding itself is unsupported. In the
[last substantive result](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-6115859156),
the reporter says a reset restored artwork and they had not successfully broken
it again. This does not confirm a fix in the current release. The issue is still
open. The original failing artifact set was not available to this investigation.

### The retained F1061 preparation failure is addressed

[`effective_cover_format`](../../src/iPodDB/library/_artwork_writing.py) chooses
new artwork's stored row count from validated retained records and MHIF, accepting
both 6,160 and 6,272 bytes with 112-byte rows. Retained geometry, allocations,
filenames, captured file bounds and overlaps are checked independently. This
also accepts supported mixtures and bounded visible dimensions. See
[ADR-0121](../adr/0121-preserve-retained-f1061-raster-height.md),
[ADR-0124](../adr/0124-accept-validated-mixed-f1061-layouts.md), and
[ADR-0131](../adr/0131-accept-bounded-visible-dimensions-in-packed-artwork.md).

Consequently, the issue's quoted failure merely because all retained thumbnails
are 6,160 bytes is not the current behavior. A tight 6,050-byte 55-by-55 payload
is still insufficient for the native 112-byte stride; do not normalize those
three reported sizes into equivalent layouts.

### Differences that remain

- The [Classic catalog](../../src/device_registry/data/catalog.py) still supplies
  F1055, F1060, F1061 and F1068 to ordinary cover creation. The
  [application policy](../../src/iOpenPod/app/artwork_policy.py) forwards that set
  without a media-kind filter. The associated-format distinction is absent from
  the catalog model. This is a producer-policy difference requiring separate
  treatment from whether a firmware importer accepts the additional thumbnail.
- F1061 still defaults to 56-by-56 at 112-byte stride (6,272 bytes). The
  [encoder](../../src/iPodDB/ArtworkDB/ithmb_writer.py) scales content into that
  raster. Retaining 6,160 bytes selects height 55 but keeps width 56. Native
  55-by-55 intrinsic geometry therefore remains distinct from newly authored
  content geometry; accepted payload length alone does not establish identical
  framing to iTunes. Changing this default would amend the explicit ADR policy,
  not repair an unexplained whole-library blank-art failure.
- [`WriteTarget`](../../src/iPodDB/library/writing.py) still uses a 256 MiB shard
  budget. Each MHNI stores the actual filename, offset and byte length;
  `append_image` rolls over before exceeding the budget and preserves captured
  prefixes. A differing iTunes rollover policy alone is not evidence of invalid
  reads. The issue's proposed 500 MiB or FAT32-limit changes are not adopted here.
- [`zero_source_size`](../../src/iPodDB/library/_artwork_timing.py) writes the
  decoded RGB888 byte count for newly supplied pixels, not the compressed source
  image file size. MHII source size and MHIT artwork size agree with each other.
  This remains an interchange-metadata difference; it is separate from the MHNI
  length that controls pixel reads.
- The [root creation policy](../adr/0033-create-artworkdb-from-catalog-capabilities.md)
  supplies MHFD +0x10 value 6 for Classic and retains existing root values. Thus
  the original unconditional-value-2 complaint does not describe current native
  Classic creation. Unknown retained header bytes remain lossless.

### Product validation and generated native-probe inputs

The following existing regression selection passed: **103 tests in 29.46 s**.

```powershell
uv run pytest tests/iPodDB/library/test_artwork_format_repair.py tests/iPodDB/library/test_artwork_sharding.py tests/iPodDB/library/test_artwork_native_verification.py tests/iPodDB/library/test_artwork_read_contract.py tests/iPodDB/library/test_artwork_creation.py tests/iPodDB/library/test_mixed_artwork_addition.py tests/iOpenPod/app/services/test_artwork_format_repair_save.py
```

These cover retained 55/56-row append, mixed geometry, real writer rollover with
independent expected pixels/filenames/offsets, fresh creation, invalid ranges,
independent output verification and publication through a virtual device. They
are software regressions, not physical Classic 7G acceptance tests.

Private generator `.scratch/issue178/generate_fixture.py` invokes the current
production Library preparation with MC293's real cover formats. Its synthetic
library has eight Tracks, four with distinct covers, and an artificial
409,600-byte cap to force two F1060 shards. The output is under
`.scratch/issue178/producer-fixture/`; `receipt.json` records every thumbnail and
file hash. ArtworkDB SHA-256 is
`a4e7d58bd96ee33c2fbe06f497bc101a8b00259dfe550e03b8c59ef004325a6f`.
The companion iTunesDB uses a synthetic unsigned test baseline and is not a
device-ready signed Sync artifact. Native routine probes must state their mocked
I/O and unexecuted paths; this fixture does not establish full firmware boot,
large-library memory behavior, USB reload or physical screen rendering.

## Disposition

No product change is justified as a demonstrated fix for the whole-library
blank-art symptom by this investigation alone. In particular, do not change the
shard cap or opaque MHFD values on the assumption that these readers require it.
The known retained-F1061 preparation refusal is addressed by current code.

The remaining authoring differences merit separate work: native F1061 content
geometry, associated F1068 selection, and provenance of source-image byte sizes.
They should not be described as a verified cause or fix for issue 178. A current
same-device reproduction would need the failing ArtworkDB, referenced thumbnail
files, iTunesDB, log and actual RetailOS release, ideally paired with a working
capture. Until then, the defensible status is **specific old failure addressed;
overall device symptom not reproduced or conclusively resolved**.
