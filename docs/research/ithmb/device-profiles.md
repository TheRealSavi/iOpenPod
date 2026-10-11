# iTHMB Device Profiles and format-ID scope

Research date: 2026-10-11.

## What a format ID establishes

A numeric ID such as `1061` is a useful correlation key inside a device's
ArtworkDB and thumbnail files. It is not sufficient evidence for a universal
pixel-layout lookup. The same ID can occur in different device families, in
different artwork roles, and in libraries written by different applications.
The sources below establish implementation choices and reported observations;
they do not establish a complete Apple specification or a firmware compatibility
matrix.

The Original iOpenPod already makes explicit Nano 7 overrides for `1013`, `1015`,
and `1016`, which otherwise describe different older-device images. Conversely,
libgpod deliberately shares one fallback table between Nano 3 and several Classic
generations. Sharing is an implementation assumption, not a separate validation
of every device to which the table is assigned.
[Original definitions][original-presets], [libgpod family assignments][libgpod-families]

For research, retain at least the Device Profile, reported firmware/build, artwork
role, format ID, source of the descriptor, database geometry and size fields,
and captured bytes. Preserve uncertainty separately for each component. A
firmware-specific variant of `1061` remains possible; none of the reviewed source
tables proves or rules out that hypothesis.

## Historical libgpod tables

These tables transcribe numeric facts from upstream libgpod revision
`7982c5554f78dde47fd006afbeff659201d6db3d`. Dimensions are **width × height in the
source's descriptor**, not necessarily the visible content bounds or sufficient
information to calculate a stored allocation. The source's encoding names are
retained; see [Pixel formats](pixel-formats.md) for their actual byte semantics.
Rows are implementation evidence,
not tested-device certifications.
[Source definitions][libgpod-definitions]

### Cover artwork

| libgpod family assignment | Format ID → descriptor dimensions | Encoding in the table |
| --- | --- | --- |
| iPod Photo/color | `1017` → 56 × 56; `1016` → 140 × 140 | RGB565 LE |
| iPod Video 1/2, commonly 5th/5.5th generation | `1028` → 100 × 100; `1029` → 200 × 200 | RGB565 LE |
| Nano 1/2 | `1031` → 42 × 42; `1027` → 100 × 100 | RGB565 LE |
| Nano 3; Classic 1/2/3 | `1061` → 56 × 56; `1055` → 128 × 128; `1068` → 128 × 128; `1060` → 320 × 320 | RGB565 LE |
| Nano 4 | `1055`, `1068` → 128 × 128; `1071`, `1084` → 240 × 240; `1074` → 50 × 50; `1078` → 80 × 80 | RGB565 LE |
| Nano 5 | `1056` → 128 × 128; `1078` → 80 × 80; `1073` → 240 × 240; `1074` → 50 × 50 | RGB565 LE |
| Early touch 1/2/3 and iPhone 1/2/3 assignments | `3001` → 256 × 256; `3002` → 128 × 128; `3003` → 64 × 64 | Recursive RGB555 LE |
| Same early touch/iPhone assignments | `3005` → 320 × 320; `3006` → 56 × 56; `3007` → 88 × 88 | RGB555 LE; table comments specify 8,192-byte and 16,384-byte padded records for `3006` and `3007` |
| `MOBILE` assignment | `2002` → 50 × 50; `2003` → 150 × 150 | RGB565 BE |

The touch/iPhone assignments are historical libgpod categories. They provide no
evidence that every later iOS version or touch generation uses the same files.
The Nano 6 appears in libgpod's model-identification table but not in this static
artwork-capabilities table; absence from the fallback table does not establish
absence of artwork support. This source does not supply a Nano 7 fallback table.
[Model records and assignments][libgpod-device]

### Photos

| libgpod family assignment | Format ID → descriptor dimensions | Encoding in the table |
| --- | --- | --- |
| iPod Photo/color | `1009` → 42 × 30; `1015` → 130 × 88 | RGB565 LE |
| iPod Photo/color | `1013` → 220 × 176 | RGB565 BE with `_90` layout marker |
| iPod Photo/color and Video 1/2 | `1019` → 720 × 480 | UYVY BE; this label alone does not explain field ordering |
| Video 1/2 | `1036` → 50 × 41; `1015` → 130 × 88; `1024` → 320 × 240 | RGB565 LE |
| Nano 1/2 | `1032` → 42 × 37 | RGB565 LE |
| Nano 1/2 | `1023` → 176 × 132 | RGB565 BE |
| Nano 3; Classic 1/2/3 | `1067` → 720 × 480 | I420 LE |
| Nano 3; Classic 1/2/3 | `1024` → 320 × 240; `1066` → 64 × 64 | RGB565 LE |
| Nano 4 | `1024` → 320 × 240; `1066` → 64 × 64; `1079` → 80 × 80; `1083` → 240 × 320 | RGB565 LE |
| Nano 5 | `1087` → 384 × 384; `1079` → 80 × 80; `1066` → 64 × 64 | RGB565 LE |
| Early touch/iPhone assignments above | `3004` → 56 × 55; `3011` → 80 × 79; `3009` → 160 × 120; `3008` → 640 × 480 | RGB555 LE; `3004` has an 8,192-byte target allocation, not 8,192 added padding bytes |

The Nano 4/5 source also mentions `1081` → 640 × 480 JPEG, but that entry is
**commented out as unimplemented**. Do not turn it into a statement that libgpod
actively supports that format. Similarly, remarks about cropping, borders and
scaling in the early touch photo table are author observations, not a general
definition of every `300x` format.
[Photo tables and comments][libgpod-definitions]

### Chapter images

libgpod assigns chapter-image tables separately from cover and Photo tables:

| Assignment | IDs and dimensions | Encoding |
| --- | --- | --- |
| Nano 3; Classic 1/2/3 | `1055` → 128 × 128; `1029` → 200 × 200 | RGB565 LE |
| Nano 4 | `1071` → 240 × 240 | RGB565 LE |

An ID's appearance in a cover table does not identify every use of that ID.
These are the explicit chapter assignments in the inspected fallback table;
missing entries are not proof that a device cannot display chapter images.
[Chapter definitions and family assignments][libgpod-families]

## Original iOpenPod and later Nano profiles

Original iOpenPod revision `a20242428b93b672d14b37230772dbad75139c69` names
libgpod and other reverse-engineering projects as inputs to its registry. Its
Nano 7 registry comment also attributes those formats to a local iTunes-authored
dump. That attribution is useful provenance, but is not a substitute for a
reproducible capture with firmware, writer version and specimen identity.
Agreement with libgpod may reflect common ancestry rather than independent
confirmation.
[Original registry and source notes][original-presets]

The following later-Nano descriptors are in Original iOpenPod and the current
iOpenPod 2.0 catalog. All use RGB565 LE in those implementations. Sizes here are
**calculated** as the implementation's row stride times height; they are not new
measurements of firmware requirements.
[Original descriptors][original-presets], [current catalog][current-catalog]

| Device Profile and role | ID | Descriptor dimensions | Row stride | Calculated raster bytes |
| --- | --- | --- | --- | --- |
| Nano 6 cover | `1073` | 240 × 240 | 480 | 115,200 |
| Nano 6 cover | `1085` | 88 × 88 | 176 | 15,488 |
| Nano 6 cover | `1089` | 58 × 58 | 116 | 6,728 |
| Nano 6 cover | `1074` | 50 × 50 | 100 | 5,000 |
| Nano 6 Photo thumbnail | `1092` | 80 × 80 | 160 | 12,800 |
| Nano 6 Photo | `1093` | 512 × 512 | 1,024 | 524,288 |
| Nano 7 cover | `1010` | 240 × 240 | 480 | 115,200 |
| Nano 7 cover | `1013` | 50 × 50 | 100 | 5,000 |
| Nano 7 cover | `1015` | 58 × 58 | 116 | 6,728 |
| Nano 7 cover | `1016` | 57 × 57 | 116 | 6,612 |
| Nano 7 Photo thumbnail | `1005` | 80 × 80 | 160 | 12,800 |
| Nano 7 Photo | `1007` | 480 × 864 | 960 | 829,440 |

Nano 7 `1016` illustrates why width × height × two is insufficient: its declared
57-pixel width is paired with 116-byte rows. It also directly conflicts with the
older Photo/color cover descriptor `1016` → 140 × 140. Nano 7 `1013` differs from
the older Photo descriptor in dimensions, endianness/layout marker and role;
`1015` differs in dimensions and role. These are explicit variant definitions in
the source, not an invented possible collision.
[Original overrides][original-presets], [current catalog][current-catalog]

The Original registry additionally carries `1020` and `1044` as compatibility
aliases. Their source comments do not identify specimen firmware or provide a
capture reference, so they remain leads rather than validated additions to the
device-family matrix.
[Alias definitions][original-presets]

## Why `1061` remains unresolved

Several different statements are easily compressed into an inaccurate claim that
`1061` simply means 55 × 55 or 56 × 56:

| Evidence | What it actually establishes | What it does not establish |
| --- | --- | --- |
| libgpod static descriptor | Writer fallback is 56 × 56 RGB565 LE; a nearby comment questions a nominal 55 × 55 size | Which firmware requires, accepts or ignores the extra row/column |
| rePear descriptor | `1061` tuple is `(55, 56)` in **height, width** order, so its generated raster is 56 × 55 and 6,160 bytes | Device-wide correctness, independence from earlier reverse engineering, or equivalence to libgpod output |
| Original iOpenPod descriptor | New images use 56 × 56 with 112-byte rows | Whether all supported physical devices accept those images |
| Latest #178 report | The reporter found 6,160-byte `1061` slots on their Classic 7, Classic 6.5 and Nano 3 specimens, despite variable visible dimensions | Firmware-specific scope, independent reproduction, or a rule for untested same-model devices |
| iOpenPod 2.0 ADR-0121/0124/0131 | The software recognizes 55- and 56-row retained rasters and certain smaller visible bounds inside them | A physical firmware validation of every accepted mixed-layout combination |

Sources: [libgpod `1061`][libgpod-1061], [rePear descriptor and constructor][repear],
[Original descriptor][original-presets],
[ADR-0121](../../adr/0121-preserve-retained-f1061-raster-height.md),
[ADR-0124](../../adr/0124-accept-validated-mixed-f1061-layouts.md),
[ADR-0131](../../adr/0131-accept-bounded-visible-dimensions-in-packed-artwork.md).

At 112 bytes per row, 55 rows occupy 6,160 bytes and 56 rows occupy 6,272 bytes.
A 55-pixel RGB565 row aligned to four bytes is also 112 bytes. Therefore width
55, stored width 56, visible height 55, a 56-row allocation, and a 55-row raster
are distinct possibilities that must not be conflated. These arithmetic
relationships explain several plausible layouts; arithmetic alone does not select
the actual one. Source dimensions, MHNI dimensions, raster byte count, allocation
byte count, row stride, padding and record-to-record offsets must be examined
together.

The [starting report in issue #178][starting-comment] should be compared against
these alternatives for its tested specimens. Its latest comment does not supply
firmware versions or raw supporting captures. See [Issue evidence](issue-evidence.md)
for the exact scope, earlier reports and counterexamples. A successful image decode on a Host
only shows that one interpretation produces a plausible image. Correct rendering
on a particular physical iPod provides stronger evidence for that specimen and
firmware; neither result establishes a global `1061` definition.

No firmware-controlled before/after experiment was performed in this research.
Firmware variation, model-specific interpretation, metadata from a different
writer, and content-versus-storage geometry are still competing explanations where
the capture does not distinguish them.

## Device-supplied metadata and its limitations

### Native keys and interpretation

The inspected libgpod parser recognizes `AlbumArt` or `AlbumArt2` for covers,
`ImageSpecifications` or `ImageSpecifications2` for Photos, and `ChapterImageSpecs`
or `ChapterImageSpecs2` for chapter images. These are the concrete keys in this
source; names such as “artwork formats” or “image formats” should not be mistaken
for a guaranteed literal plist key.
[List parsing][libgpod-parser-lists]

| Descriptor field | Meaning or treatment in the inspected implementation |
| --- | --- |
| `FormatId` | Numeric correlation ID |
| `RenderWidth`, `RenderHeight` | Requested raster dimensions |
| `DisplayWidth` | Distinct display width; libgpod's structure documentation marks it unused |
| `PixelFormat` | Hexadecimal string representing a pixel-format FourCC, mapped as below |
| `PixelOrder` | For `L555`, presence of this key selects libgpod's recursive RGB555 decoder; the parser does not interpret its value |
| `RowBytesAlignment` | Row-byte alignment requirement, not itself the row stride |
| `AlignRowBytes` | Older Boolean form; libgpod maps true to alignment 4 when no numeric alignment is set |
| `Crop`, `Rotation`, `BackColor` | Additional rendering policy recorded by the parser |
| `Interlaced`, `ColorAdjustment`, `GammaAdjustment`, `AssociatedFormat` | Parsed metadata; the structure documentation marks these unused, with `AssociatedFormat` also described as unknown |

Sources: [field mapping and conversion][libgpod-parser],
[descriptor structure][libgpod-structure]. “Parsed” does not mean every writer
actually implements the field.

| `PixelFormat` string | FourCC | libgpod interpretation |
| --- | --- | --- |
| `32767579` | `2vuy` | UYVY BE |
| `42353635` | `B565` | RGB565 BE |
| `4C353635` | `L565` | RGB565 LE |
| `79343230` | `y420` | I420 LE |
| `4C353535` | `L555` | RGB555 LE, or recursive RGB555 LE when `PixelOrder` is present |

These are the strings accepted by this parser, not a complete catalog of every
Apple pixel format. Unrecognized strings cause that descriptor to be dropped.
An apparently empty parsed format list can therefore reflect parser coverage as
well as what the device supplied.
[Pixel-format conversion][libgpod-parser]

### Query response, cache and generated metadata are different evidence

libgpod describes `SysInfoExtended` as a saved copy of information queried from a
device, not a standard file that must have been written by iTunes. Its documentation
also distinguishes transport coverage: on Nano 5, the SCSI response may omit artwork
formats and SQL postprocessing data that the USB control response exposes. A
missing field in one response is consequently not evidence that a capability is
absent. Save the raw response, query method and capture time alongside any parsed
descriptor list.
[libgpod provenance and transport notes][libgpod-sqlite],
[libgpod overview][libgpod-overview]

The inspected libgpod selectors use fallback tables when no parsed extended
metadata object exists. If the object exists, they return its corresponding list;
they do not automatically merge a missing list with the static table. This is a
particular program's selection policy, not an Apple requirement or a recommended
universal confidence ordering.
[Format selection][libgpod-selection]

iOpenPod 2.0 adds another provenance hazard. Its metadata-reconciliation code can
populate `AlbumArt` and `ImageSpecifications` from the built-in Device Profile,
writing `RowBytes` and enum-style `PixelFormat` values such as `RGB565_LE`.
Those are not the same spelling/representation as the native fields accepted by
the libgpod parser above. Such a file records application policy; rereading it
cannot independently corroborate that policy as a hardware observation.
This is a source-level distinction, not a newly reproduced interoperability bug.
[Current metadata synthesis][current-authority],
[ADR-0013](../../adr/0013-reconcile-device-metadata-across-existing-boundaries.md)

Original iOpenPod also falls back to inferred RGB565 LE with `width * 2` stride
when observed dimensions match neither a preferred Device Profile nor the global
registry. This is useful behavior to understand in old captures, but those inferred
encoding and stride values must not be cited as device-reported facts.
[Original resolver][original-resolver]

## Evidence needed to refine a Device Profile

For each new observation, record a pseudonymous specimen identifier, exact model
and hardware revision when available, firmware/build and how it was obtained,
writer application/version, clean-versus-existing-library state, and the queried
metadata's provenance. Keep original ArtworkDB/PhotosDB and bounded iTHMB ranges
with hashes; avoid committing personal library contents or serial numbers.

Evaluate cover, Photo, chapter-image and TV-output roles separately. Record which
physical screen or output was exercised, because a correct small cover does not
validate Cover Flow, full-screen Photos or TV output. Use known asymmetric test
images with marked edges, color ramps and non-square content so padding, rotation,
pixel order and subsampling errors are distinguishable.

The strongest next evidence for a firmware hypothesis is the same specimen with
controlled firmware/writer changes and retained before/after captures, followed by
replication on another specimen. Until then, record compatibility as an observed
combination of specimen, firmware, writer and layout. Treat untested combinations
as unknown rather than filling them from a same-model or same-ID match.
The [validation plan](validation-and-open-questions.md) expands these experiments.

The existing Device Registry boundary can describe known variants, while iPodDB
interprets database bytes and the Application Layer composes their evidence. This
research identifies a need to retain provenance; it does not silently replace the
accepted catalog or F1061 write policy with a new architectural decision.
[ADR-0012](../../adr/0012-load-artwork-lazily-across-existing-boundaries.md),
[current catalog][current-catalog]

[libgpod-device]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c
[libgpod-definitions]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L442-L587
[libgpod-families]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L580-L621
[libgpod-1061]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L561-L569
[libgpod-parser]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_sysinfo_extended_parser.c#L226-L475
[libgpod-parser-lists]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_sysinfo_extended_parser.c#L512-L543
[libgpod-structure]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.h#L121-L164
[libgpod-selection]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L1309-L1367
[libgpod-sqlite]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/README.sqlite
[libgpod-overview]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/README.overview
[original-presets]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/device/artwork_presets.py
[original-resolver]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/device/artwork.py#L78-L144
[current-catalog]: https://github.com/TheRealSavi/iOpenPod/blob/e6fa69065edc5858277b818fe5ccee1925566eeb/src/device_registry/data/catalog.py
[current-authority]: https://github.com/TheRealSavi/iOpenPod/blob/e6fa69065edc5858277b818fe5ccee1925566eeb/src/device_registry/authority.py#L447-L473
[repear]: https://github.com/worstje/repear/blob/7ca8bbd704ee247e15cf9bccdb85a94b1d53d768/iTunesDB.py#L451-L480
[starting-comment]: https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-6106769456
