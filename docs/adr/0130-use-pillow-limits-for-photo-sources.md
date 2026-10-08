# ADR-0130: Use Pillow limits for Photo sources

- Status: Accepted
- Date: 2026-10-08
- Amends: ADR-0056 and ADR-0086

## Context

Photo preparation imposed an 8,192-pixel edge and 32-megapixel area limit on
originals as well as generated thumbnails. Ordinary 6,016-square wallpapers
exceeded that area limit despite being readable by Pillow and representable in
PhotosDB. Increasing only the preparation limit would still leave validation and
full-resolution previews rejecting those same Photos.

## Decision

Use Pillow's unchanged decompression-bomb thresholds for Photo sources. Do not
disable or raise its global pixel limit or add another decoder dependency.
Host scanning, Photo preparation, and Host/device previews share path-free source
inspection and viewing-image preparation. Reduce the image before EXIF orientation
and RGB conversion so those operations copy the small working raster. JPEG decoding
can use Pillow's draft reduction; other formats can still allocate a source raster.

Retain original encoded bytes and dimensions when the source is within the existing
64 MiB encoded-size bound and its dimensions fit PhotosDB's unsigned 16-bit fields.
The old application source-dimension limits no longer apply. Generated thumbnail
rasters retain their existing bounds and device-format validation. Independent
original verification still uses Pillow and compares captured dimensions and bytes.

Sources beyond the encoded-size bound or PhotosDB's 65,535-pixel edge use the existing
first-frame PNG viewing copy fitted within 4,096 by 4,096 pixels. Pillow's own source
limits still apply to that conversion. The Host original is unchanged; the Library
Sync Helper retains its separate Host digest so the converted Photo remains In sync
on subsequent scans. Full-resolution preview accepts the same 64 MiB encoded bound
as publication, while iTHMB reads keep their separate 32 MiB range bound.

## Consequences

6K square images, 16K widescreen images, and long panoramas within Pillow's limits
can be scanned, prepared, verified, published, and previewed. Original export stays
lossless when conversion is unnecessary. A 16K square image exceeds Pillow's current
hard pixel threshold and remains rejected. Compressed size alone does not bound
decoding memory; the unchanged Pillow guard and one-at-a-time Photo preparation
remain relevant. This policy does not promise arbitrary image dimensions or change
the thumbnail formats supported by an iPod.
