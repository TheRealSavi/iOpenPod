# iTHMB `2vuy` / UYVY decoding notes

## Scope and conclusion

These notes establish the byte layout needed to decode the 720-by-480 iTHMB
TV-output format normally stored in `F1019_N.ithmb`. The request called the
format `UVYY`, but no primary source examined here uses that name. Apple's name
is `2vuy`, and the conventional byte-order name is UYVY.

The important result is that an iPod F1019 frame is **not an ordinary row-major
UYVY raster**. Each row still consists of conventional UYVY two-pixel blocks,
but all even output rows form the first stored field and all odd output rows form
the second stored field. Decoding the bytes as 480 consecutive display rows
therefore stacks or combs the two fields and cannot produce the correct image.

The evidence used here is, in descending order of authority:

- Apple's Core Video definition of `2vuy` for component order, and Apple's
  QuickTime technical note for its Rec. 601 component ranges;
- libgpod's mature iPod-specific reader, writer, SysInfo parser, and device
  format tables at fixed commit `7982c555`;
- Keith Wiley's independently reverse-engineered iPod Photo Reader at fixed
  commit `c15481b7`, which corroborates the F1019 field layout; and
- read-only measurements from the connected iPod Classic. That device carries
  F1067/I420 rather than F1019/UYVY, so it validates the neighboring format and
  the physical-raster rules but is not a direct F1019 sample.

## Name and component order

Apple defines `kCVPixelFormatType_422YpCbCr8` as 8-bit 4:2:2 Y'CbCr ordered
`Cb Y'0 Cr Y'1`, and identifies the corresponding codec type as `2vuy`.
Apple also describes the smallest addressable `2vuy` block as two pixels in 32
bits. Therefore, the four bytes for horizontal pixels `x` and `x + 1` are:

```text
byte 0  Cb / U, shared by both pixels
byte 1  Y' for pixel x
byte 2  Cr / V, shared by both pixels
byte 3  Y' for pixel x + 1
```

This is `[U, Y0, V, Y1]`, not literal `[U, V, Y0, Y1]`.
[Apple's pixel-format definition](https://developer.apple.com/documentation/CoreVideo/kCVPixelFormatType_422YpCbCr8)
and [block-width documentation](https://developer.apple.com/documentation/corevideo/kcvpixelformatblockwidth)
are explicit about this order. Microsoft's packed-YUV description independently
uses the same four-byte UYVY macropixel and explains that it performs 2:1
horizontal chroma subsampling with no vertical subsampling.
[Microsoft UYVY documentation](https://learn.microsoft.com/en-us/windows/win32/medfound/recommended-8-bit-yuv-formats-for-video-rendering#422-formats-16-bits-per-pixel)

libgpod maps the SysInfoExtended pixel-format string `32767579`, the hexadecimal
ASCII spelling of `2vuy`, to its `THUMB_FORMAT_UYVY_BE` identifier.
[libgpod SysInfo mapping](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_sysinfo_extended_parser.c#L390-L407)
Despite the `BE` suffix, libgpod's reader and writer access four individual
bytes in the order above and never use their byte-order argument for this
format. A byte-oriented decoder must not swap 16-bit or 32-bit words.
[libgpod reader](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L565-L629)
[libgpod writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L547-L655)

## Exact F1019 storage layout

libgpod's device tables assign format ID 1019 to a 720-by-480 UYVY image for
both iPod Photo and iPod Video device families.
[libgpod iPod Photo table](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L448-L453)
[libgpod iPod Video table](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L519-L524)
Keith's observed-device table independently identifies F1019 on fourth-generation
iPod Photo and fifth-generation iPod Video as 720-by-480, 16-bit YCbCr 4:2:2,
"Interlaced Shared Chrominance."
[Keith's observed format table](https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/README.txt#L68-L96)

The fixed geometry is:

| Quantity | Value |
| --- | ---: |
| Stored width | 720 pixels |
| Stored height | 480 rows |
| Bytes per two-pixel block | 4 |
| Row stride | 1,440 bytes |
| Rows per field | 240 |
| Bytes per field | 345,600 (`0x54600`) |
| Bytes per frame | 691,200 (`0xA8C00`) |

The frame has two field-contiguous halves:

```text
offset 0x00000 .. 0x545ff  output rows 0, 2, 4, ..., 478
offset 0x54600 .. 0xa8bff  output rows 1, 3, 5, ..., 479
```

Within either field, rows and two-pixel blocks are ordinary row-major UYVY.
There is no evidence of 8-by-8, 16-by-16, Morton, or other macroblock tiling.
The only block is the standard two-horizontal-pixel UYVY macropixel; the only
raster reordering is the separation of even and odd rows. Both libgpod's
[unpacker](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L565-L629)
and [packer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L611-L655)
use this mapping. Keith's independent decoder computes the same first-field and
second-field addresses from output-row parity.
[Keith's decoder](https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/main.cp#L445-L565)

For fixed F1019 geometry, the direct addressing rule is:

```python
width = 720
height = 480
stride = width * 2
field_bytes = (height // 2) * stride

for y in range(height):
    field_offset = 0 if y % 2 == 0 else field_bytes
    row_offset = field_offset + (y // 2) * stride
    for x in range(0, width, 2):
        i = row_offset + x * 2
        cb, y0, cr, y1 = payload[i : i + 4]
```

An equivalent preprocessing step is to weave the stored rows before ordinary
UYVY conversion:

```python
stored = np.frombuffer(payload[:691_200], np.uint8).reshape(480, 1440)
linear = np.empty_like(stored)
linear[0::2] = stored[:240]
linear[1::2] = stored[240:]
```

If a layout descriptor supports an explicit stride, the general row address is
`field_base + (y // 2) * row_bytes`, and the second field begins after
`(height // 2) * row_bytes`. F1019 itself has no extra per-row padding:
`row_bytes == width * 2`.

## RGB conversion

Apple states that `2vuy` follows Rec. 601 component ranges: nominal Y' is
16 through 235, while Cb and Cr are centered at 128 with nominal range 16
through 240. It is a storage-format 4:2:2 representation in which each pair of
luma samples shares one chroma pair.
[Apple QuickTime TN2307](https://developer.apple.com/library/archive/technotes/tn2307/_index.html)

For RGB888 output, apply the standard limited-range BT.601 conversion separately
to `Y0` and `Y1`, reusing the pair's Cb and Cr:

```text
C = Y  - 16
D = Cb - 128
E = Cr - 128

R = clip((298*C + 409*E + 128) >> 8)
G = clip((298*C - 100*D - 208*E + 128) >> 8)
B = clip((298*C + 516*D + 128) >> 8)
```

These integer equations and their floating-point derivation are published in
Microsoft's official BT.601 conversion guidance.
[Microsoft conversion equations](https://learn.microsoft.com/en-us/windows/win32/medfound/recommended-8-bit-yuv-formats-for-video-rendering#converting-8-bit-yuv-to-rgb888)
They also exactly invert, subject to quantization and chroma subsampling, the
limited-range coefficients libgpod uses when it writes F1019 bytes.
[libgpod forward transform](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L611-L650)

Useful diagnostic vectors are:

| UYVY bytes | Expected RGB pair |
| --- | --- |
| `80 10 80 10` | black, black |
| `80 EB 80 EB` | white, white |
| swapped Cb/Cr | recognizable image with red/blue hue inversion |

Do not copy libgpod's decoder formula character-for-character: its second
pixel's red expression uses `Y0` while its green and blue expressions use `Y1`,
an apparent one-channel typo. The layout evidence remains consistent, but a
correct decoder uses `Y1` for all three channels of the second pixel.
[libgpod affected lines](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L596-L601)

Nearest-neighbor replication of the shared Cb and Cr samples to both horizontal
pixels is the minimum correct rendering. A higher-quality chroma upsampler can
interpolate horizontally, but it is not necessary to establish the format and
must not change the field-weaving rule.

## iTHMB range and padding rules

An iTHMB file is a flat sequence of already-encoded image records, not a file
with a per-frame F1019 header. Keith's reverse-engineering notes describe images
of one format and resolution concatenated into files that may continue into a
new numbered shard.
[Keith's container description](https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/README.txt#L27-L31)

ArtworkDB or PhotosDB supplies the authoritative format ID, filename, byte
offset, image size, dimensions, and padding. libgpod reads those MHNI values and
then seeks to the recorded offset and reads exactly the recorded size.
[libgpod MHNI projection](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-image-parser.c#L76-L113)
[libgpod bounded read](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L631-L688)

The safe decode order is therefore:

1. Select the Device Profile's format descriptor by MHNI format ID.
2. Read exactly the MHNI offset and image-size range from the named iTHMB shard.
3. Validate that an F1019 record is at least 691,200 bytes.
4. Decode the complete 720-by-480 physical raster using the field-separated
   layout.
5. Apply any evidenced visible-region crop only after physical decoding.

Dimensions used to locate planes or fields must be the physical format
dimensions, not an MHNI visible dimension reduced by padding. Otherwise every
row after the first and every subsequent plane starts at the wrong byte.

## Distinct variants

The pixel encoding and the raster storage order should be modeled separately.
Generic UYVY can be ordinary row-major, while the evidenced iPod F1019 profile
is UYVY with separated even and odd fields. Applying field weaving to every
future UYVY profile would be as incorrect as omitting it for F1019. A precise
descriptor should express both facts, for example `UYVY_422` plus
`FIELD_SEPARATED`, or one unambiguous `UYVY_422_FIELDS` layout.
The iOpenPod implementation uses `UYVY` for generic row-major storage and
`UYVY_FIELDS` for the F1019 field-contiguous variant.

F1067 is not an F1019 variant. libgpod identifies it as 720-by-480 `I420_LE` for
iPod Classic and third-generation iPod Nano devices.
[libgpod F1067 table](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L571-L576)
Its meaningful image data begins with a full Y plane followed by quarter-size Cb
and Cr planes. libgpod nevertheless requires and writes a two-byte-per-pixel
record, leaving an additional half-byte-per-pixel tail beyond the conventional
12-bit I420 planes.
[libgpod F1067 reader](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L525-L563)
[libgpod F1067 writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L467-L544)
Keith's observed table calls this "12-bit YCbCr 4:2:0, Blue first, half image
padded," distinguishing it from F1019's interlaced 4:2:2 form.
[Keith's F1067 observations](https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/README.txt#L93-L119)

## Connected-iPod experiment

The connected device was inspected read-only. Its SysInfoExtended identifies an
iPod Classic and declares:

```text
FormatId     1067
PixelFormat  I420_LE
RenderWidth  720
RenderHeight 480
RowBytes     1080
```

The Photo Database contains 16 referenced Photos. Each F1067 MHNI range is
691,200 bytes, while `Photos/Thumbs/F1067_1.ithmb` is 11,750,400 bytes, exactly
17 records. The extra unreferenced record is consistent with iTHMB being an
appendable raw frame store whose database ranges determine live membership.

For the first referenced record:

- the first 345,600 bytes are a 720-by-480 Y plane;
- the next 86,400 bytes are a 360-by-240 Cb plane;
- the next 86,400 bytes are a 360-by-240 Cr plane;
- the final 172,800 bytes are an auxiliary packed field; its Y samples exactly
  reproduce source Y rows 241, 243, ..., 479, while its Cb/Cr samples closely
  reproduce the lower half of the planar chroma.

Decoding the conventional first 518,400 bytes as 720-by-480 I420 produces a
coherent image. That image has eight black columns on each side and 704 active
columns. The corresponding MHNI reports width 704 and horizontal padding 8.
Thus the stored physical raster is 720 pixels wide, and using
`MHNI width + one padding value` as the plane width would incorrectly produce
712. This empirically confirms that physical format geometry must establish
plane offsets before any visible-region crop.

The pre-fix iOpenPod 2.0 implementation constructed symmetrically padded Photo
layouts from the MHNI width, then derived I420 plane sizes from that resulting
stored width. For this connected-device record, that path started Cb 3,840 bytes
too early, shifted both chroma planes, and returned a 696-by-480 crop. This was a
separate F1067 failure from the F1019 row-major UYVY failure, but the common
correction was to decode the complete Device Profile raster first and crop only
afterward.

The pre-fix path has a per-channel mean absolute error of 58.942 against the
retained full-resolution original resized to the decoded dimensions. Using the
Device Profile's 720-pixel physical width before cropping returns the evidenced
704-by-480 active raster and reduces the same error measure to 13.445.

## Implementation and test implications

The research supports these deterministic requirements:

- replace the current generic row-major F1019 path with field-separated row
  addressing;
- keep the byte group as `Cb, Y0, Cr, Y1`; never decode `UVYY` literally and
  never byte-swap it;
- use limited-range BT.601 conversion and `Y1` for all channels of the second
  pixel;
- validate even width, even height, stride at least `width * 2`, and payload
  length at least `row_bytes * height`;
- retain generic row-major UYVY as a distinct possible layout rather than
  changing its meaning globally without a profile discriminator;
- use physical Device Profile dimensions and stride to locate rows and planes,
  then apply MHNI visible-region padding/cropping; and
- keep F1067's two-byte-per-pixel record contract distinct from its 12-bit
  meaningful planar image data.

At minimum, tests should include:

1. A four-row synthetic F1019 fixture with distinct luma per output row, stored
   as rows `0, 2, 1, 3`, and assertions that decode order is `0, 1, 2, 3`.
2. A UYVY block with distinct `Y0` and `Y1` values to catch libgpod's historical
   second-red-channel typo.
3. Black and white limited-range vectors (`Y=16` and `Y=235`).
4. A Cb/Cr-asymmetric vector to catch plane or component swapping.
5. Exact F1019 size/stride checks at 720 by 480.
6. A standard row-major UYVY fixture proving that only the F1019 storage profile
   gets field weaving.
7. A 720-by-480 F1067 record with MHNI width 704 and padding 8 proving that plane
   offsets use 720, not 712.
