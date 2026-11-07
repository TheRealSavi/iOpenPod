# ADR-0144: Expand Track headers with device capabilities

- Status: Accepted
- Date: 2026-10-14
- Extends: [ADR-0100](0100-reconcile-firmware-playback-sidecars-on-device-selection.md)
- Extended by: [ADR-0145](0145-select-track-layouts-for-all-library-writes.md),
  including device-aware new Track creation and later derived fields.
- Amended by: [ADR-0171](0171-use-standard-track-headers-on-mini-2-and-ipod-video.md),
  selecting 624-byte headers for Mini 2G and full-size iPod 5G/5.5G.
- Corrected by: [ADR-0195](0195-adopt-firmware-database-field-semantics.md):
  the total skip counter fits a 156-byte header; the secondary counter and
  last-skipped date do not. Expansion and preservation policy remain in force.

## Context

An iPod nano 6G can contain a 156-byte MHIT while reporting skip history in a
playback sidecar. That header lacks the last-skipped date. Keeping its extent while merging
the history makes serialization fail; discarding the fields makes consumption
lose understood evidence. Original iOpenPod selected larger headers from the
device's database version, but rebuilt records rather than retaining their bytes.
The [research note](../research/short-track-headers-and-playback-history.md) records
the 1.x implementation, device profiles, and captured nano 5G/6G/7G layouts.

## Decision

The Application supplies the selected Device Profile's binary database version
through `WriteTarget.database_version`. iPodDB owns the version-to-MHIT-size policy
beside the shared Chunk definition: versions through `0x12`, `0x19`, and `0x2D`
select 156, 328, and 504 bytes respectively; later versions select 624 bytes.
These are expansion targets, not an enumeration of valid retained header sizes.
The retained MHBD version alone never authorizes expansion.

Library reconciliation expands an existing Track only when an intended native
field cannot fit and the supplied capability can accommodate it. No-op preparation,
unchanged Tracks, and unrelated edits retain their original extent. Existing larger
or nonstandard headers are never shrunk. New Track creation keeps its existing
policy. Low-level parsing and serialization never expand headers implicitly.

Expansion retains existing bytes outside the requested edits, including Unknown
Data, children, trailers, and floating-point representations. Newly allocated bytes
use the shared definitions' defaults. Newly exposed secondary persistent identity,
played state, bookmark, artwork-presence, video, and purchase mirrors are seeded
from retained identity and semantic intent. Other optional native fields retain
their defaults unless explicitly edited. Existing noncanonical native fields are
not normalized. Partial opaque fields retain their original prefix; expansion
through a partial numeric field is rejected because its missing bytes have no
established meaning. An actual expansion raises the root database version to at
least the supplied device baseline and never downgrades a newer source version.

Verification derives the expected extent and newly exposed fields from original
data and intent, independently of the writer's candidate. It checks native
identities, opaque bytes, semantic history, and the database version after reparse.
The same transaction continues to publish the signed/compressed database, SQLite
artifacts where required, and exact sidecar archives through Storage.

Playback projection always retains understood evidence. Missing or insufficient
capabilities, unsafe boundaries, or verification failures block preparation; they
never permit consumption of partially represented history. Original database bytes
and pending sidecars remain available under the existing recovery contract.

## Consequences

Nano 5G, 6G, and 7G share the 624-byte policy. Nano 5G continues to use HASH72;
nano 6G/7G use HASHAB. All three retain compressed-database and SQLite handling.
Earlier nano 1G/2G and full-size 5G/5.5G profiles select 328 bytes; nano 3G/4G and
Classic profiles select 624. Model-name exceptions are unnecessary for this issue.

Tests cover short-header history, both sidecar formats, signing, SQLite, repeated
selection, unsupported capabilities, partial boundaries, and preservation. Retained
captures support the format choice; physical firmware acceptance remains untested.
