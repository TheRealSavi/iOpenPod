# iTHMB pixel encodings and raster layout

Research date: 2026-10-11. This is a source-based survey, not a firmware
specification or a report of new physical-device testing. Format IDs below are
examples within the cited source's device tables. Neither an ID nor a marketing
model name establishes a universal layout across devices, firmware, or producers.
See the [evidence rules](README.md#how-to-interpret-evidence),
[database range fields](container-and-index.md#mhni-fields), and
[Device Profile tables](device-profiles.md) for the surrounding interpretation.

The useful separation is **component encoding**, **byte order**, **pixel order**,
**stored raster geometry**, **visible region**, and **allocation size**. A valid
description needs all of these. Correct RGB565 bit masks do not determine whether
an F1061 record has 55 or 56 stored rows. Correct UYVY component order does not
determine whether its rows are field-separated.

## What the primary implementations actually recognize

libgpod's SysInfoExtended parser recognizes the following hexadecimal ASCII
`PixelFormat` values. These are properties outside the raw pixel payload, not
magic bytes at the start of an iTHMB record. Its `L555` interpretation selects
recursive ordering when a `PixelOrder` key exists; it does not validate every
possible value of that key. That is an implementation rule, not proof that any
future `PixelOrder` value means the same layout. [libgpod SysInfo parser][sysinfo]

| Descriptor spelling | ASCII | libgpod interpretation |
| --- | --- | --- |
| `4C353635` | `L565` | RGB565, little-endian words |
| `42353635` | `B565` | RGB565, big-endian words |
| `4C353535` | `L555` | RGB555, little-endian words; possibly recursive ordering |
| `32767579` | `2vuy` | UYVY; the codec accesses individual bytes |
| `79343230` | `y420` | Planar Y, Cb, Cr; the codec accesses individual bytes |

The parser separately reads `RenderWidth`, `RenderHeight`, `DisplayWidth`,
`Interlaced`, `Crop`, `Rotation`, `BackColor`, `ColorAdjustment`,
`GammaAdjustment`, `AssociatedFormat`, and `RowBytesAlignment`. Parsing a
descriptor does not prove that libgpod implements every property: its type
documentation explicitly marks several fields unused. Keep captured values even
when their effect is not understood. [Parser fields][sysinfo-fields],
[descriptor documentation][format-struct]

## Packed RGB565 and RGB555

For the packed layouts in libgpod, each pixel occupies a 16-bit word. The following
equations describe its masks after the word has been read in the selected byte
order. `p` is the decoded unsigned word; input RGB channels are eight-bit values.
[Bit masks][masks], [RGB writer][rgb-writer]

| Layout | Word interpretation | Encode RGB888 by truncation |
| --- | --- | --- |
| RGB565 | `R=(p>>11)&31`, `G=(p>>5)&63`, `B=p&31` | `((r>>3)<<11) | ((g>>2)<<5) | (b>>3)` |
| RGB555 | `R=(p>>10)&31`, `G=(p>>5)&31`, `B=p&31` | `(flag<<15) | ((r>>3)<<10) | ((g>>3)<<5) | (b>>3)` |

For a red RGB565 pixel the word is `0xF800`: bytes are `00 F8` in little-endian
storage and `F8 00` in big-endian storage. Byte-swapping and exchanging red/blue
channels are different operations; a BGR interpretation must have separate
evidence. Neither the Host CPU nor the ArtworkDB integer byte order alone selects
the pixel-word order.

RGB555's high bit must not automatically be called a proven alpha channel.
libgpod's writer explicitly says its meaning is uncertain and sets it for ordinary
image pixels; the reader discards it. Retain its original value when preserving a
record. [RGB555 writer][rgb555-writer], [RGB readers][rgb-readers]

libgpod expands channel values by left shift only. Thus maximum five-bit and
six-bit values become 248 and 252, not 255. A display decoder can instead replicate
high bits (`v5<<3 | v5>>2`, `v6<<2 | v6>>4`) or scale with a stated rounding rule.
These are reconstruction policies; they do not change the stored bit fields.
Comparisons against another decoder must account for that difference before
calling a byte layout incorrect. [libgpod reconstruction][rgb-readers]

## Recursive RGB555: pixel order, not word-byte swapping

libgpod's `REC_RGB555` first uses the RGB555 word packing above, then recursively
orders square quadrants as **top-left, bottom-left, top-right, bottom-right**.
Within each quadrant it repeats the same rule until individual pixels remain.
Its touch-era cover table assigns this representation to 3001, 3002, and 3003
at 256, 128, and 64 pixels square respectively. These are source-table claims;
they do not establish all touch-era firmware. [Recursive packer][recursive-write],
[recursive reader][recursive-read], [touch table][touch-table]

For a power-of-two square, the equivalent pixel index is a Morton-style
interleaving with **y in the low bit** of each bit pair:

```text
index(x,y) = sum((bit(y,k) << (2*k)) | (bit(x,k) << (2*k+1)))
byte_offset = 2 * index(x,y)

2-by-2 pixel indices:
0 2
1 3
```

This equation is derived from the cited recursion. A convention placing x in the
low bit would transpose the order. Square power-of-two geometry is a necessary
precondition for this simple derivation; the source's square check is not evidence
that arbitrary odd-sided squares, rectangles, or padded rows work. Do not replace
`REC_RGB555` with ordinary RGB555 plus an endian toggle.

## UYVY / 2vuy and field-separated rows

Conventional UYVY stores two horizontal pixels as `Cb, Y0, Cr, Y1`, with shared
chroma and independent luma. Apple's `2vuy` uses Rec. 601 component ranges;
nominal luma is 16–235 and chroma is centered at 128. The byte layout alone does
not imply field separation. [Packed component order][linux-uyvy],
[Apple color-range definition][apple-yuv]

libgpod's 1019 table entries for Photo and Video families use a 720-by-480 raster.
Its reader and writer store even display rows first, then odd display rows.
Keith's implementation independently uses that addressing for its interlaced
shared-chroma mode. For that specific unpadded layout:

```text
row_bytes = 1440
field_bytes = 345600
frame_bytes = 691200
row_offset(y) = (y % 2) * field_bytes + floor(y / 2) * row_bytes
pair_offset(x,y) = row_offset(y) + 2*x       # even x
```

The two halves are fields of one image, not two full images. These facts support
the cited 1019 profile; they do not make every future `2vuy` descriptor
field-separated. Despite libgpod's `UYVY_BE` name, its codec does not byte-swap the
four byte components. [1019 device entries][photo-video-tables],
[libgpod UYVY codec][uyvy-read], [Keith row addressing][keith-uyvy]

A limited-range BT.601 conversion applies separately to each pixel's own luma:

```text
C = Y - 16; D = Cb - 128; E = Cr - 128
R = clip8((298*C + 409*E + 128) >> 8)
G = clip8((298*C - 100*D - 208*E + 128) >> 8)
B = clip8((298*C + 516*D + 128) >> 8)
```

These are rounded integer approximations, not a byte-exact inverse of a lossy
RGB-to-subsampled-YCbCr conversion. libgpod's historical UYVY reader uses the first
pixel's luma for the second pixel's red channel, apparently a defect: do not copy
that expression. [Microsoft conversion equations][microsoft-yuv],
[affected libgpod expressions][uyvy-read]

The [earlier UYVY investigation](../ithmb-uyvy-format.md) has a fuller address
walkthrough. Its strong wording about F1019 should be read within the source and
sample scope above, not as an exhaustively tested firmware guarantee.

## Planar 4:2:0 and the extra F1067 tail

In ordinary contiguous eight-bit I420, Y has `W*H` samples and Cb and Cr each have
`W*H/4` samples for even W and H. Each chroma sample serves a two-by-two luma block.
Plane order is Y, Cb, Cr; swapping the chroma planes gives a different layout.
Subsampling does not determine allocation length, color range, or unused bytes.
[Planar format terminology][linux-planar]

libgpod's 1067 entry uses 720-by-480 I420 and requires a **691,200-byte** record,
although the three decoded planes use only **518,400 bytes**. [1067 table][classic-table],
[I420 reader][i420-read]

| Region | Offset | Length | Interpretation in the cited decoder |
| --- | ---: | ---: | --- |
| Y | 0 | 345,600 | 720-by-480 luma |
| Cb | 345,600 | 86,400 | 360-by-240 blue chroma |
| Cr | 432,000 | 86,400 | 360-by-240 red chroma |
| Tail | 518,400 | 172,800 | Not read by libgpod's planar decoder |

For this tight planar geometry, chroma sample index is
`floor(y/2)*(W/2) + floor(x/2)`. Derive it from the stored raster width, not the
visible crop width. This does not describe separate plane strides, odd
dimensions, or a tiled YUV representation. [I420 reader][i420-read]

The tail is **not established as disposable zero padding**:

- Keith's reader advances by two bytes per pixel and comments that the extra
  area contains a cropped image. [Keith allocation choice][keith-i420]
- `ithmbrdr` reports F1067 from one nano 3rd generation and describes recognizable
  packed YCbCr information after the planes. Its README's tail length is
  arithmetically incomplete: `720*120` is 86,400, whereas the remaining quarter of
  a `720*480*2` record is 172,800 bytes. Preserve the observation without adopting
  that length as a specification. [Author's report][ithmbrdr-report]
- The repository's [earlier connected-device experiment](../ithmb-uyvy-format.md#connected-ipod-experiment)
  records a Classic sample whose tail luma reproduces rows 241, 243, …, 479 and
  whose chroma resembles the lower half of the planar image. This is inherited
  evidence from that report; no device was remeasured for this note.
- libgpod's writer allocates `2*W*H` but only explicitly assigns the first
  `1.5*W*H` bytes. Its output does not reconstruct the observed auxiliary field.
  [I420 writer][i420-write]

The auxiliary field's firmware purpose and required writer behavior remain open.
Successful planar display does not prove that replacing the tail with zeros is
safe for TV output or every firmware. Preserve retained bytes.

Color reconstruction is also incompletely established for the full I420 family.
libgpod applies limited-range BT.601-like coefficients; `ithmbrdr` uses a
full-range JPEG-style matrix and explicitly asks which conversion is best.
That disagreement needs known-color source images and raw-device comparisons;
visual recognizability alone cannot settle it. [libgpod conversion][i420-read],
[ithmbrdr conversion][ithmbrdr-code]

## Geometry, row alignment, padding, and transforms

For a supported linear 16-bit raster with stored width W, height H, and byte-row
alignment A divisible by two, the derived row stride is `2*W` if A is zero,
otherwise `ceil((2*W)/A)*A`; pixel offset is `y*stride + 2*x`. Raster byte count is
`stride*H`. These equations model libgpod's RGB alignment helper, not arbitrary
iTHMB codecs. Its older `AlignRowBytes` compatibility rule supplies alignment 4
when a newer nonzero `RowBytesAlignment` is absent. [RGB alignment][rgb-writer],
[legacy alignment mapping][sysinfo]

Keep these different regions separate:

| Kind | Effect | Evidence |
| --- | --- | --- |
| Row alignment | Bytes between consecutive stored rows | RGB alignment helper |
| Visible-region border/crop | Which portion of an existing raster is presented | MHNI dimensions and offsets; producer-dependent interpretation |
| Encoding-internal auxiliary tail | Bytes inside the encoded image-data range but unused by the main planar decoder | F1067's 172,800-byte tail is included in libgpod's 691,200-byte image size |
| Allocation padding after image data | Bytes reserved after the encoded image-data range | Touch table's 8,192/16,384-byte allocation targets |

libgpod calls its allocation target `padding`, but its writer subtracts the
encoded image length before adding zeros. For example, its 3006 target is 8,192
bytes for a 56-by-56 RGB555 raster, so the addition is 1,920 bytes, not 8,192.
[Touch targets][touch-table], [allocation writer][allocation]
This is distinct from F1067's internal tail and from the separate MHNI allocation
extension used by other writers; see [MHNI fields](container-and-index.md#mhni-fields).

For ordinary scaling, libgpod preserves aspect ratio, rounds the reduced
dimension upward, and centers the result using integer division. With `Crop`
enabled, it scales to fill and crops centrally. These describe that producer's
policy, not mandatory iTunes behavior. Likewise, the writer reports MHNI
dimensions inclusive of its leading padding, while the reader accommodates
negative crop offsets and clipped bounds. Other captured records must be
interpreted from their own evidence. [Scaling and cropping][scaling],
[writer metadata][dimensions-write], [reader bounds][dimensions-read]

Orientation is another independent dimension. libgpod lists 1013 as
`RGB565_BE_90`, but the reader routes `_90` variants through the ordinary unpacker
with an explicit unfinished-treatment comment. Its source-EXIF rotation path
does not prove the on-device storage rotation for that profile. A corner-labelled
fixture with original image, raw bytes, metadata, and actual display result is
needed to fix direction and crop order. [1013 table][photo-video-tables],
[rotation dispatch][rotation], [source transforms][scaling]

F1061 demonstrates why dimensions must stay explicit: the repository records
6,160-byte and 6,272-byte RGB565 rasters, corresponding to 112-byte rows at heights
55 and 56. A visible 55-pixel-wide region does not force a 110-byte stride.
[ADR-0121](../../adr/0121-preserve-retained-f1061-raster-height.md) and
[ADR-0131](../../adr/0131-accept-bounded-visible-dimensions-in-packed-artwork.md)
record current software policy and its evidence limits. They do not prove that
all firmware accepts both rasters.

## Additional families and evidence limits

- **RGB888:** libgpod defines 32-bit words with eight-bit RGB fields and an
  additional high byte. This is not tightly packed three-byte RGB. Its writer
  nevertheless has 16-bit return/intermediate variables in this path; the mere
  presence of an enum and codec does not establish a dependable writer or a
  device profile. [Masks][masks], [RGB888 implementation][rgb888]
- **JPEG:** libgpod's nano 4th/5th generation tables contain commented-out 1081
  JPEG entries marked unimplemented. They are leads, not sample validation.
  A JPEG payload must be examined as a bounded compressed representation; a
  guessed `width*height*2` length is inappropriate. [Table comments][jpeg-table]
- **CL versus CLCL:** Keith's `CL` helper tries one byte containing two four-bit
  chroma components plus one luma byte per pixel. His `CLCL` helpers instead
  extract full eight-bit Cb, Y0, Cr, Y1 from a four-byte pair. Calling that CLCL
  helper a nibble-chroma codec misreads the source. No device assignment for the
  nibble-chroma experiment is established here. [Keith helpers][keith-chroma]
- **Other decoder options:** Keith offers swapped-plane 4:2:0, alternative
  32-bit channel arrangements, and grayscale experiments. Options in a recovery
  tool are hypotheses, not a list of formats proven to exist on every iPod.
  [Keith method dispatch][keith-i420]

The established code and reports cover important families, but do not close the
format. Outstanding evidence includes firmware-specific color transforms, the
1067 auxiliary field, exact rotated-profile semantics, RGB555 high-bit meaning,
and reliable geometry for every device/producer combination. A synthetic
encode/decode round trip validates internal agreement; physical acceptance and
interoperability need separately attributed device observations.

## Source pins and independence

libgpod links use `gtkpod/libgpod` commit
`7982c5554f78dde47fd006afbeff659201d6db3d`. Its codecs were also compared with
`fadingred/libgpod` HEAD `4a8a33ef4bc58eee1baca6793618365f75a5c3fa`; the writer,
reader, and mask header are byte-identical. Those mirrors are one evidence family.
Keith's source is pinned to `c15481b7abeb5750d6264ba9d1800787977294d8` and
`ithmbrdr` to `d9de0d2cadd2ba116f20eef2a203a40ca6fb3f5c`.

`ithmbrdr` credits Keith as its main format reference, so agreement between their
algorithms is not entirely independent; the nano device account adds separately
attributed observation. Apple's and Microsoft's documents define generic pixel
representations and color math, not iPod profile assignments. A later decoder
that copies iOpenPod's tables cannot independently corroborate those same tables.

[sysinfo]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_sysinfo_extended_parser.c#L390-L474
[sysinfo-fields]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_sysinfo_extended_parser.c#L225-L248
[format-struct]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.h#L121-L166
[masks]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-image-parser.h#L37-L80
[rgb-writer]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L71-L182
[rgb555-writer]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L184-L212
[rgb-readers]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L305-L358
[recursive-write]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L397-L465
[recursive-read]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L391-L470
[touch-table]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L533-L559
[linux-uyvy]: https://docs.kernel.org/userspace-api/media/v4l/pixfmt-packed-yuv.html#subsampling
[apple-yuv]: https://developer.apple.com/library/archive/technotes/tn2307/_index.html
[photo-video-tables]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L441-L524
[uyvy-read]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L565-L629
[keith-uyvy]: https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/main.cp#L445-L565
[microsoft-yuv]: https://learn.microsoft.com/en-us/windows/win32/medfound/recommended-8-bit-yuv-formats-for-video-rendering#converting-8-bit-yuv-to-rgb888
[linux-planar]: https://docs.kernel.org/userspace-api/media/v4l/pixfmt-yuv-planar.html
[classic-table]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L561-L577
[i420-read]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L525-L563
[keith-i420]: https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/main.cp#L570-L685
[ithmbrdr-report]: https://github.com/cyianor/ithmbrdr/blob/d9de0d2cadd2ba116f20eef2a203a40ca6fb3f5c/README.md
[i420-write]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L467-L544
[ithmbrdr-code]: https://github.com/cyianor/ithmbrdr/blob/d9de0d2cadd2ba116f20eef2a203a40ca6fb3f5c/main.go#L25-L46
[allocation]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L890-L917
[scaling]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L696-L832
[dimensions-write]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L994-L1017
[dimensions-read]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L812-L884
[rotation]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L725-L767
[rgb888]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L291-L394
[jpeg-table]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L477-L510
[keith-chroma]: https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/main.cp#L268-L316
