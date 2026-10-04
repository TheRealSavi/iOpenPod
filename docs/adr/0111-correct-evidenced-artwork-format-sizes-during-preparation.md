# ADR-0111: Correct evidenced artwork format sizes during preparation

- Status: Accepted
- Date: 2026-10-04
- Extends: ADR-0021 and ADR-0033; replaces ADR-0033's unconditional refusal of conflicting MHIF image sizes.

## Context

A Nano 7 user reported that artwork preparation refused format 1010 because its
retained MHIF size was 87,552,000 rather than the 115,200 bytes in one image. The
reported corrections for formats 1013, 1015, and 1016 also match the Device Profile,
including format 1016's row padding. A synthetic reproduction confirms that the
size mismatch alone causes the refusal; the user's original database is not a
captured fixture.

The [foo_dop source](https://github.com/reupen/ipod_manager/blob/main/foo_dop/photodb.cpp)
updates file-list sizes to thumbnail file end positions during truncation and
serializes those values into MHIF. This supports a compatibility repair without
assuming every mismatch was produced by foo_dop. The user requested automatic
correction without a separate confirmation.

## Decision

When preparing newly encoded cover artwork, iPodDB automatically corrects a
conflicting retained MHIF size if the target's fixed-size encoding and every
retained MHNI representation of that format establish the same image size. Both
MHNI size fields must match. Dimensions and padding must describe the target
raster, including the centered-content bounds used by foo_dop. Every representation
must have one filename and fit within a captured, fingerprinted thumbnail file.
Shared identical ranges are allowed; partial overlaps are not. Missing images,
ambiguous representations, inconsistent evidence, and variable-size JPEG layouts
continue to block preparation with expected and recorded sizes in the diagnostic.

Only the affected MHIF image-size fields are corrected. Retained image locations,
thumbnail bytes, Unknown Data, and unrelated formats remain unchanged. Correction
is logged during preparation and requires no additional UI, setting, or approval.
Parsing, unchanged serialization, and unrelated edits remain lossless. This is
neither repair on device selection nor a general ArtworkDB cleanup operation.

The Application Layer already captures thumbnail inventories and fingerprints.
Full shards require only their captured fingerprint and range bounds, since their
contents are not changed. Independent output verification checks the corrected
size against newly generated images. Storage publishes the resulting candidate
through the existing transaction, revalidating dependencies and retaining originals
for recovery without relying on optional Backup Snapshots.

## Consequences

Users can Sync artwork onto an otherwise consistent library with stale MHIF sizes
without manually patching device bytes. Unverifiable layouts still fail safely.
Synthetic Nano 7 regressions cover all four reported values; virtual-volume tests
cover publication, restoration, and concurrent thumbnail changes. These tests
establish software behavior, not validation on the reporter's physical iPod.
