# ADR-0131: Accept bounded visible dimensions in packed artwork

- Status: Accepted
- Date: 2026-10-08
- Amends: ADR-0111 and ADR-0124

## Context

A retained F1061 MHNI can describe a 55-by-56 visible image inside a 56-by-56
RGB565 raster with 112-byte rows and 6,272 bytes. The existing decoder reads this
layout, but artwork preparation rejects it because the visible width neither
fills the raster nor combines with declared padding to fill it. This reproducible
case can send Sync through ADR-0125's fallback, leaving new Tracks without covers.
Mixed visible dimensions alone do not make the stored rasters incompatible.

Original iOpenPod's packed decoder distinguishes visible dimensions from the
stored row stride, and its writer preserves mixed retained representations. Its
F1061 definition supplies 56-by-56 pixels for new artwork. These behaviors support
preserving valid visible bounds without requiring every retained image to fill
the raster or describe exactly centered content.

## Decision

For packed RGB565 and RGB555 variants, including rotated RGB565, validate retained
MHNI visible dimensions independently of the fixed raster size when the format
declares an explicit positive row stride.
For each axis, require `0 <= padding < dimension <= raster dimension`. The visible
dimension need not equal the raster dimension, and visible dimension plus padding
need not equal it. Existing fixed-size, representation, filename, fingerprint,
file-bound and allocation-overlap checks still apply.

F1061 retains ADR-0124's independently validated 55-row and 56-row raster sizes,
allocation rules, and output selection: prefer a retained MHIF size found among
valid rasters, otherwise their most common size with the Device Profile breaking
ties. New images fill the selected output raster, including 56-by-56 when that
layout is selected. Retained visible dimensions do not shrink new images or change
the output-size policy. Existing MHNI records, thumbnail bytes, and locations stay
unchanged; new artwork is appended and verified through the ordinary preparation
and recoverable Storage Transaction.

Packed formats with an implicit row stride, UYVY, field-separated UYVY, I420, and
JPEG retain their existing validation rules. Implicit stride depends on visible
dimensions; subsampling, field or plane offsets, and embedded dimensions also
require separate format evidence before relaxing geometry. This decision changes
cover preparation, not PhotosDB geometry or lazy decoding. Unverifiable artwork
still follows the existing preparation failure and Sync fallback policies.

## Consequences

Valid mixed visible sizes such as 55-by-56 and 56-by-56 no longer prevent new cover
artwork in a supported packed raster. Zero or oversized dimensions, invalid
padding, unsupported raster sizes, truncated allocations, and conflicting overlaps
still fail validation. Synthetic regressions establish software behavior and
retained-byte preservation; they do not establish physical firmware compatibility
for previously unsupported raster encodings.
