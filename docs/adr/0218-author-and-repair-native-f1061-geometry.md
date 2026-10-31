# ADR-0218: Author and repair native F1061 geometry

- Status: Accepted
- Date: 2026-10-31
- Amends: ADR-0121, ADR-0124, ADR-0131, ADR-0202, ADR-0203

## Context

Independent firmware checks establish F1061 as **55 by 55 RGB565 pixels with
112-byte rows** on Classic 6, 6.5, both 7G updater families, and nano 3. Each row
contains 110 visible pixel bytes and two padding bytes. Video 5/5.5 advertise
F1028/F1029 instead. There is no evidenced 56-by-56 model variant to preserve in
Device Registry. See the [firmware matrix](../research/f1061-native-geometry.md).

The prior 56-by-56 authoring default followed Original iOpenPod and confused row
storage with visible geometry. A native reader can accept 6,272 bytes without
making the extra column or row visible. Acceptance of an oversized allocation
does not establish correct resampling. The owner requested correct authoring and
automatic correction of existing affected libraries.

## Decision

Device Registry supplies 55-by-55, 112-byte-row F1061 for every profile that
advertises that format. New images use 6,160 bytes, including zero row padding.
Retained MHIF values and legacy sizes do not override this native authoring
geometry. Preserve the existing distinction between visible bounds, primary
pixel read length and allocated file extent.

Normal Library preparation automatically examines retained F1061 records when
the selected target supplies this exact native layout. Pending repair participates
in the existing Artwork repair state, so Sync can publish it without media edits.
Selection and lossless serialization alone do not rewrite device bytes. The pure
iPodDB pass runs after ordinary candidate verification and before returning the
Prepared Library; Storage remains the only device writer.

For proven 112-byte-row legacy rasters, decode their own bounded visible geometry
and resample genuine 56-pixel content to 55 by 55. Write corrected pixels to fresh
F1061 shards, update only their thumbnail geometry and location fields, and keep
identities, Artwork Display Times, other formats and Unknown Data. Never overwrite
or repack existing shards. Correctly framed 55-pixel content with a 6,272-byte
primary extent needs only a 6,160-byte read length; keep its full original
allocation and exact pixel bytes. Already-correct 6,160-byte rasters may retain
larger allocations and bounded cropped dimensions.

Use a valid F1055/F1060 representation of the same image at the same Artwork
Display Time when the F1061 source cannot establish a safe raster. In particular,
6,050 bytes alone cannot distinguish a tight 110-byte row layout from truncated
112-byte rows, so it must not be repaired by changing its length or guessing its
stride. Do not use a different Chapter time or associated video thumbnail as a
fallback. Missing, unsupported or ambiguous sources remain unchanged with a
warning; another valid record may still be corrected. A changed captured
fingerprint fails preparation or publication rather than authorizing a repair.

MHIF's nominal size becomes 6,160 only when no F1061 repair is deferred. New cover
authoring retains its ordinary independent MHIF validation. A caller supplying a
non-native/custom layout does not authorize this automatic format correction.
No shard-limit or F1068 selection policy changes are included.

## Validation and recovery

The Application Layer captures source files, including full shards and explicitly
named nested paths. iPodDB validates file dependencies, geometry, complete raster
and allocation extents, and overlap evidence before decoding. Fresh names reserve
captured files, existing metadata references and unavailable paths. New buffers
use the caller's bounded staging implementation and respect the target file cap.

Independent repair verification checks native dimensions and sizes, pixel hashes,
row padding, fresh paths and contiguous non-overlapping output allocations. It
undoes only authorized header/filename changes in reparsed output and requires
the original candidate bytes exactly, including opaque data and trailing bytes.
Ordinary iTunesDB and unrelated-artifact verification remains in place. The same
transaction checks captured preconditions, publishes ArtworkDB and fresh files,
and supports rollback. Backup Snapshot configuration is not a prerequisite.

Regressions cover canonical new output, real resampling of the last row/column,
55/56-row retained layouts, larger allocations, same-time fallback, missing
sources, changed fingerprints, repeated saves, model gating, virtual-device
publication/recovery, and no-media-change Sync with cancellation. Firmware probes
execute isolated native routines with adapted services; full hardware rendering
and large-library device acceptance remain separate from these checks.
