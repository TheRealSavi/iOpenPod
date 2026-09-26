# ADR-0085: Preserve positional playback sidecars during Sync

- Status: Accepted
- Date: 2026-09-26
- Extends: ADR-0029, ADR-0030 and ADR-0076

## Context

A normal `Play Counts` file prevented every Track membership change. The file
contains pending playback evidence indexed by the original database Track order.
On-The-Go Playlist files also refer to Track positions. Deleting these files or
ignoring their positions would lose or misattribute listening history and Playlist
membership.

The format evidence is libgpod's `playcounts_read` and `process_OTG_file` in
[itdb_itunesdb.c](https://github.com/gtkpod/libgpod/blob/master/src/itdb_itunesdb.c).
The current Original iOpenPod baseline contains the same unconditional sidecar
gate; its presence does not establish a completed reconciliation implementation.

## Decision

iPodDB provides a pure byte transformation for `mhdp` Play Counts rows and `mhpo`
On-The-Go indexes, including their reversed byte order. Storage supplies bounded
captures; the Application Layer supplies original and desired Track identities.

Play Counts rows stay opaque. Surviving rows and unknown header bytes are retained
exactly, reordered to follow their Tracks. Rows for explicitly removed Tracks are
removed. Trailing added Tracks have no invented history records. Inserting a new
Track before retained pending rows is rejected because unknown row fields have no
established defaults. An append-only change reproduces the original file exactly.

On-The-Go indexes are remapped to surviving Track positions, retaining duplicates,
order, unknown row extensions, and unknown header bytes. References to explicitly
removed Tracks are removed. Layout bounds and references are validated before
output is supplied to Storage.

Captured sidecars are included in the Library transaction as unchanged dependencies
or verified replacement writes. New sidecars and edits after Review still block
publication. Replacement originals participate in the same recovery journal as
the Library and media. `.bak` and `.backup` files are not active firmware inputs.
Other pending sidecar formats can be retained unchanged for append-only changes;
changes to existing Track positions remain blocked for unsupported formats.

## Consequences

Ordinary playback history no longer prevents Sync. History remains in its sidecar;
this change does not apply play-count deltas to the Library Snapshot or implement
Back Sync. It avoids interpreting undocumented playback flags and does not discard
them. Malformed records retain their originals and report the specific file.

Validation uses authored binary fixtures and virtual Storage volumes. Real-device
playback and firmware sidecar consumption remain hardware acceptance work.
