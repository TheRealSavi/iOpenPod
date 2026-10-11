# iTHMB container and database index

Research date: 2026-10-11. Read the [evidence rules](README.md#how-to-interpret-evidence)
before treating a writer convention as a firmware requirement.

## Files and responsibilities

In the historical filesystem layouts, album artwork normally lives in
`iPod_Control/Artwork/ArtworkDB` and `iPod_Control/Artwork/F<format>_<shard>.ithmb`.
Photos use `Photos/Photo Database` and `Photos/Thumbs/F<format>_<shard>.ithmb`.
The libgpod writer explicitly distinguishes these directories and emits the
corresponding colon-separated database references. The shard suffix selects a
physical file; it is not an image ID or a format version.
[libgpod naming and directory selection](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L659-L685)
[directory creation](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L1113-L1158)

For these raw formats, each file is a store of image bytes, often concatenated
fixed-size representations. There is no universal iTHMB file header, per-image
header, or file-internal table of contents. The `F1061` text belongs to a filename,
not the first four pixel bytes. Keith's independent reverse-engineering notes
describe concatenated images and continuation files. A JPEG-backed representation
can have a JPEG header inside its own range; that does not create a universal
iTHMB header.
[Keith's format notes](https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/README.txt)
[encoding variants](pixel-formats.md)

Embedded artwork in an MP3 or MP4 is source material for a synchronization writer;
it is not the same artifact as the separately indexed iTHMB representation.
Likewise, a full-resolution Photo reference is distinct from a reduced thumbnail.
The Original iOpenPod Photo workflow has separate paths for full-resolution files
and packed thumbnails. No claim here rules out additional firmware behavior.
[Original Photo workflow](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/photos.py)

## Lookup chain

```text
iTunesDB Track association              PhotosDB Photo / Photo Album membership
                 \                       /
                  MHII image identity
                         |
                 MHOD image representation(s)
                         |
                 MHNI format + range + geometry
                         |
                 MHOD type 3 path
                         |
                 named iTHMB shard + offset + bounded bytes
                         |
                 device-specific layout -> decoded pixels -> visible region
```

The numeric format ID, MHII image identity, iTunesDB Track database ID, and shard
number are separate values. Depending on the database generation, Track association
can use an MHII reverse Track reference or a direct artwork link in a later Track
header. Shared artwork can associate multiple Tracks with one image; shared byte
ranges and shared MHII identities are also different kinds of sharing.
[Original artwork writer](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/artworkdb_writer/artwork_writer.py)
[current creation policy](../../adr/0033-create-artworkdb-from-catalog-capabilities.md)

ArtworkDB and PhotosDB share much of their Chunk grammar:

| Container | Meaning relevant to iTHMB |
| --- | --- |
| `mhfd` | Database root. |
| `mhsd` type 1 -> `mhli` -> `mhii` | Images and their representation children. |
| `mhii` -> `mhod` type 2 -> `mhni` | Common thumbnail representation path. |
| `mhni` -> `mhod` type 3 | Filename or path for the representation. |
| `mhsd` type 2 -> `mhla` -> `mhba` -> `mhia` | Photo Albums and image membership. |
| `mhsd` type 3 -> `mhlf` -> `mhif` | Format/file-list declarations; not necessarily one entry per shard. |

Full-resolution type-5 records and auxiliary type-6 records need their own
interpretation. In particular, not every type-6 body is an MHNI: the repository
retains an opaque MHAF form. Photo MHII fields must not automatically inherit
album-art Track-link semantics.
[shared structure declarations](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-itunes-parser.h#L529-L652)
[ArtworkDB grammar and auxiliary data](../artworkdb-format.md)
[PhotosDB semantics](../photosdb-format.md)

For ordinary little-endian iPod databases, a Chunk begins with a four-byte marker,
a 32-bit header length, and a 32-bit extent field. List Chunks `mhli`, `mhla`, and
`mhlf` use that third field as a child count, not a byte length. Header lengths are
declared in the file: observed defaults are not permission to hard-code traversal
past longer headers. Database byte order and pixel byte order are independent.
libgpod also has endian-reversed mobile-phone database paths, outside this
dossier's primary iPod scope.
[libgpod structures](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-itunes-parser.h)
[byte-order-aware string writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c#L271-L356)

## MHNI fields

Offsets below are relative to the beginning of MHNI, not the beginning of the
iTHMB file. The table describes the ordinary little-endian layout. Width/height
signedness is not uniformly expressed by historical programs: libgpod uses signed
16-bit members, while iOpenPod uses unsigned dimension fields. Values with the
high bit set are not validated large-image evidence.

| Offset | Width | Interpretation and qualification |
| --- | --- | --- |
| `0x00` | 4 bytes | `mhni` marker. |
| `0x04` | u32 | Header byte length. |
| `0x08` | u32 | Total Chunk extent including children. |
| `0x0C` | u32 | Child count. |
| `0x10` | u32 | Format ID, historically also called correlation ID. |
| `0x14` | u32 | Byte offset relative to the named image file. |
| `0x18` | u32 | Encoded image-data length in the inspected readers/writers. |
| `0x1C` | i16 | Vertical padding/origin field. |
| `0x1E` | i16 | Horizontal padding/origin field. |
| `0x20` | 16 bits | Height/bottom-bound field; not sufficient to establish stored row count. |
| `0x22` | 16 bits | Width/right-bound field; not necessarily the row stride. |
| `0x24` | u32 when present | Unresolved generally; foo_dop interprets as display start time in milliseconds. |
| `0x28` | u32 when present | foo_dop's padded allocation length; iOpenPod calls it `image_size_2`. Legacy libgpod does not populate this extension. |

The common prefix is directly visible in
[libgpod's MHNI declaration](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-itunes-parser.h#L577-L591)
and [range projection](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-image-parser.c#L76-L113).
The extension and fallback for older short records are visible in
[foo_dop's reader](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L1036-L1064).
The local [shared Chunk definition](../../../src/iPodDB/ArtworkDB/shared/chunk_defs/mhni.py)
is the implementation's single source of offsets. These notes describe evidence;
they are not another definition table for production code to consume.

Two equal length fields are common, but equality is not a format-wide invariant.
foo_dop assigns data length to `0x18` and padded size to `0x28`. Its missing-extension
fallback is the data length. An older writer leaving an extension zero is different
from a measured zero-length image. Preserve the raw fields and apply an explicitly
scoped interpretation instead of overwriting one with the other.
[foo_dop write assignments](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L712-L736)
[libgpod MHNI writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c#L363-L400)

## Paths and string payloads

For a common 24-byte MHOD header, the historical type field is 16 bits at `0x0C`,
the string-padding count is one byte at `0x0F`, string byte length is at `0x18`,
encoding byte at `0x1C`, and string bytes at `0x24`. With longer retained
headers, the string prefix starts at the declared header end. Ordinary type-3
paths are UTF-16LE with encoding indicator 2 and separately recorded padding.
The writer examples are `:F1060_1.ithmb` for covers and
`:Thumbs:F1067_1.ithmb` for Photos.
[libgpod string layout](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-itunes-parser.h#L340-L398)
[string serialization](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c#L271-L356)

A reader must resolve these within the artifact's allowed Device Path root.
Do not convert arbitrary colon-delimited data into unrestricted Host paths.
Do not reconstruct a filename solely from the format ID when an explicit name
exists: the shard number and retained path carry information. These are safety
requirements from the [repository architecture](../../source_architecture.md#paths),
not reverse-engineered firmware facts.

## Geometry: four quantities that must remain separate

| Quantity | Example for a candidate F1061 layout | What determines it |
| --- | --- | --- |
| Visible content | 55 by 55 pixels | Crop/origin interpretation and MHNI evidence. |
| Stored raster | 55 rows of 112 bytes | Pixel layout, row stride, and data length. |
| Allocation | 6,160 bytes, or potentially a larger padded reservation | Writer convention and the MHNI extension where evidenced. |
| Shard length | Many allocations plus gaps or unreferenced bytes | Actual filesystem object, not the image's size field. |

These are illustrative alternatives, not a declaration that every F1061 uses
them. With RGB565, a 112-byte row can hold 56 words while only 55 columns are
visible. `112 * 55 = 6160`; `112 * 56 = 6272`; tightly packing 55 by 55 gives
6,050 bytes. Those three numbers encode different assumptions.

foo_dop writes the MHNI width as `content_width + left_origin` and height as
`content_height + top_origin`, with origins in the padding fields. libgpod does
the same in its thumbnail writer. Thus subtraction recovers visible dimensions
for that writer convention; adding the padding is not universally sufficient to
recover the physical raster. Odd margins, unused columns, rotation, and planar
formats require independent storage geometry.
[foo_dop geometry](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L724-L736)
[libgpod geometry](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L1007-L1022)

## MHIF is evidence, not a universal stride oracle

The commonly used MHIF prefix has format ID at `0x10` and a 32-bit size field
at `0x14`. libgpod calls this `image_size` and writes `width * height * 2`.
Its file-list writer emits entries per format. That formula does not account for
every row alignment or variable-size encoding, and the record is not an inventory
entry for every physical shard.
[libgpod file-list writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c#L731-L808)

foo_dop initializes its corresponding field from format size, but later cleanup
code assigns thumbnail file end positions and serializes those values. This is
inspectable evidence of writer-dependent semantics, consistent with the large
MHIF values reported on Nano 7. It does not identify which writer produced any
particular user's database. Original iOpenPod instead chooses the most common
retained/generated image size when several sizes occur.
[foo_dop file-size updates](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L176-L198)
[MHIF serialization](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L1322-L1336)
[Original iOpenPod writer](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/artworkdb_writer/artwork_writer.py)

Consequently, do not walk an entire shard by repeatedly adding MHIF size unless
a specific corpus establishes that invariant. Prefer each MHNI's bounded range.
An offset delta can reveal allocation or alignment, but gaps, shared references,
deleted entries, and mixed writers can make it larger than one image.

## Shards, offsets, and rollover

| Evidence | Actual number or behavior | Permitted conclusion |
| --- | --- | --- |
| libgpod `ITHUMB_MAX_SIZE` | 256,000,000 decimal bytes; comment attributes reduction from 500 MB to interface slowness. Existing offset is checked before the next write. | Historical writer policy; one image may cross its threshold. |
| foo_dop allocation | Checks prospective end against `500 * 1024 * 1024` = 524,288,000 bytes, with format offset alignment. | Another writer policy; its loop's file-count limit is also software-specific. |
| #178 latest report | Full F1060 files reportedly exactly 524,288,000 bytes. | Observation for the reporter's iTunes-generated samples, pending raw evidence. |

[libgpod constant](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L51-L55)
[libgpod rollover](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L1032-L1065)
[foo_dop allocator](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L242-L275)
[#178 observation](https://github.com/TheRealSavi/iOpenPod/issues/178#issuecomment-6106769456)

At 320 by 320 RGB565, 204,800 bytes per image divides 524,288,000 exactly into
2,560 slots. The arithmetic is consistent with the report; it does not prove
that a shard must reach this size, that smaller shards fail, or that every format
shares the same limit. A 32-bit offset is an addressing field, not proof that
firmware accepts a near-4-GiB shard.

The database determines live references. Unreferenced records, alignment gaps,
reserved bytes, and deleted-image remnants can remain in a file. libgpod's
fixed-size compactor requires uniform image sizes, then moves images and adjusts
all references to a shared offset. It is not an algorithm for safely compacting
arbitrary mixed-size libraries. File divisibility and a coherent decoded image
are useful recovery clues but do not recover Track associations reliably.
[libgpod compaction](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L1231-L1378)

## Read and preservation checklist

This is a proposed investigation/implementation checklist, not a new ADR:

1. Identify the database artifact, Device Profile evidence, and writer provenance.
2. Parse declared Chunk extents and counts; retain unrecognized bytes and fields.
3. Resolve image association and the exact representation path and offset.
4. Establish a layout candidate from scoped evidence, including pixel order,
   raster order, physical geometry, stride, and any allocation rule.
5. Validate file bounds using checked arithmetic: `0 <= offset <= file_length`
   and `0 < length <= file_length - offset`. Check allocation bounds separately
   from data bounds when their meanings are established.
6. Distinguish identical shared ranges from partial overlaps or conflicting
   interpretations. Preserve gaps and unreferenced bytes during investigation.
7. Decode the physical raster, then apply the evidenced visible-region rule.
8. Compare against known source images and independent decoding; record ambiguity.
9. Before any later mutation, validate all live references, stage bytes, verify
   the candidate database and ranges, and publish through Storage's recoverable
   transaction. Optional Backup Snapshots are not a prerequisite for safety.

No checksum, compression flag, universal record delimiter, or format-discovery
header for these raw payloads was established by the inspected implementations.
Integrity must be checked through lengths, references, retained bytes, and an
external capture hash; absence of a discovered field is not proof that no other
iTHMB family has one.
