# ADR-0124: Accept validated mixed F1061 layouts

- Status: Accepted
- Date: 2026-10-07
- Extends: ADR-0111 and ADR-0121

## Context

ADR-0121 accepts uniform F1061 libraries with either 55 or 56 stored rows but
rejects a mixture before validating individual images. A synthetic reproduction
with two consistent, non-overlapping rasters produces the reported blocking Sync
error. The screenshot alone does not establish the actual device's size fields.

Original iOpenPod 1.x preserves mixed payload sizes and uses the most common size
for MHIF. Each MHNI supplies its own file offset and size. The
[foo_dop writer](https://github.com/reupen/ipod_manager/blob/main/foo_dop/photodb.cpp)
also distinguishes raster data size from padded allocation size in the two MHNI
size fields. Neither mixed sizes nor unequal fields alone prove corruption.

## Decision

For F1061 RGB565 with a 112-byte row stride, validate each retained raster using
its own 6,160-byte (55-row) or 6,272-byte (56-row) layout. Its allocation must be
one of those sizes and at least as large as its raster. This permits a 55-row
raster in a 56-row allocation. Dimensions and padding must match the raster;
captured file bounds and overlap checks use the entire allocation. Identical
shared ranges are allowed; sharing an allocation with different raster lengths
is rejected. Existing filename, representation and fingerprint checks remain.

New images use a retained MHIF size if that size occurs among the validated
rasters. Otherwise use the most common retained raster size, with the Device
Profile breaking ties. Uniform libraries therefore still correct stale MHIF
sizes. Empty libraries retain ADR-0121's policy. New MHNI records and MHIF agree
on the selected output size; retained MHNI records keep their individual sizes.

Preparation and output verification use this same policy. Existing thumbnail
bytes and locations remain unchanged, new rasters are appended, and publication
still uses the recoverable Storage Transaction. Unrelated edits remain lossless.
Unsupported sizes, truncated allocations, conflicting overlaps and unverifiable
representations remain blocking errors. Other formats retain their existing rules.

## Consequences

Valid mixed F1061 layouts no longer block adding cover artwork. The policy
preserves an existing recognized MHIF declaration rather than switching it merely
because one variant has become more common. Synthetic preparation regressions
cover both output sizes, padded allocations, unchanged retained artwork, unsafe
ranges, stale MHIF correction and full-shard allocation. These checks establish
software behavior; physical mixed-layout firmware compatibility remains unverified.
