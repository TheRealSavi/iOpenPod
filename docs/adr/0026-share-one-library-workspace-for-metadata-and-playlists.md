# ADR-0026: Share one Library Workspace for metadata and Playlists

- Status: Accepted
- Date: 2026-09-05
- Extends: ADR-0022 and ADR-0025

## Context

Sidebar renaming, Track context menus, manual metadata editing, and library-wide
tag normalization need the same draft and review guarantees as Playlist editing.
A second metadata overlay would create competing desired snapshots and make stale
dialogs, model refreshes, and save authorization harder to reason about.

## Decision

Rename the Playlist Workspace to Library Workspace and extend its desired snapshot
with Track metadata and the device name. Its loaded snapshot remains immutable.
Dialogs and context menus capture a generation and edit revision. Applying an edit
requires that exact revision and an unlocked workspace. All selected Tracks validate
before any replacement is published. Each batch publishes one edit revision and
refreshes shared Track, album, collection, and Playlist projections. Reverting or
loading another Library restores all draft fields together.

iPodDB exposes validated metadata field edits through its existing Library seam.
The writer's field ownership decides which fields are editable; form descriptions
and input controls belong to iOpenPod. Omitted or mixed form values remain unchanged
unless explicitly selected for application. Native identities, media facts, artwork
references, and derived fields remain read-only. Source-dependent binary validation
still runs during preparation. Field edits are transient input to the workspace,
not another authoritative writer model.

One Track context menu serves tables and grids. A collection resolves to all its
Tracks; metadata edits deduplicate Track identities, while Playlist operations
retain occurrences. Removing and moving Playlist items operate on entry identities
so duplicate Tracks retain their private metadata. Reordering requires the complete
Playlist in natural order. Smart Playlists and folders reject direct entry edits.

Normalization preserves the ordered rules from Original iOpenPod: text cleanup,
compilation inference and propagation, featured-artist cleanup, album-artist
unification, same-name album disambiguation, and library-wide sort consistency.
Device Registry capabilities select the relevant profile. Scanning runs in a
cancellable worker over immutable Tracks, followed by a searchable preview and an
explicit Apply to Draft action. Edits, reloads, locking, or cancellation invalidate
the preview. Fourteen captured Original results provide independent parity evidence;
the Original project is not a runtime or test dependency.

The same revision-bound scan also supplies the Normalize Tags Sidebar badge. It
counts proposed field edits rather than affected Tracks, hides zero or unavailable
counts, and refreshes after a short debounce when the Library Workspace changes.
The Application Layer owns this read-only scan for the Active iPod, so opening and
closing its preview can reuse the result without restarting it. Locking, device
changes, cancellation, and shutdown still invalidate pending work. Applying remains
an explicit full-batch Library Draft edit regardless of preview filters.

The reviewed single-file save now accepts metadata, device naming, and Playlist
changes. Track identities, ordering, media facts, ArtworkDB, and artwork assets must
remain unchanged. The coordinator still accepts only its exact issued review and
rechecks source fingerprints and signing identity before Storage publishes iTunesDB
with a recovery copy and journal. Verification precedes source adoption. General
Sync, media conversion, chapter splitting, artwork replacement, and file export
remain separate workflows, as requested.

## Consequences

There is one unsaved Library state and one review/save workflow. Renaming changes
the Master Playlist title rather than the Host volume label. Metadata edits do not
rewrite media-file tags or reevaluate unrelated Smart Playlists. No new dependency
or direct device mutation outside Storage is introduced.
