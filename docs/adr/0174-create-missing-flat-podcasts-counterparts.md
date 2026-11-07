# ADR-0174: Create missing flat Podcasts counterparts

- Status: Accepted
- Date: 2026-10-24
- Amends: ADR-0024's counterpart completeness requirement

## Context

A reported iPod Video 5.5G Library has matching Master and ordinary Playlists in
datasets 2 and 3, but its special Podcasts Playlist exists only in dataset 3.
The whole-dataset completeness check blocks every new ordinary or Smart Playlist
because that Podcasts counterpart is absent.

Original iOpenPod can create this layout: `_sync_podcast_playlist_membership`
adds a new special Podcasts Playlist to its dataset-3 list, while the writer
preserves explicitly supplied dataset lists independently. Another inspected iPod
has the same special Podcasts identity in both datasets, with grouped Episodes in
dataset 3 and flat membership in dataset 2. Both layouts are valid source data.
The maintainer chose to create a missing flat counterpart on affected writes and
retain existing counterparts when both are already present.

## Decision

When a write affects Playlist datasets, create a missing special Podcasts row in
an existing dataset 2 from its retained dataset-3 counterpart before checking
dataset completeness. Identify the special Playlist by its native marker, not
its title. Require exactly one dataset of each type, one special source row, and
no existing target row with either its identity or another special Podcasts
marker. Conflicts retain the established blocking behavior.

Reuse the flattening logic for creating an entire dataset-2 companion. Preserve
the Playlist identity, header, settings, other metadata, and duplicate Episode
occurrences. Omit show-group rows and clear Episode group references, retain
Episode row IDs and position metadata, and allocate fresh occurrence persistent
identities. Preserve the grouped source and existing counterparts unless the
requested edit changes them. Reconcile requested Podcast edits against both rows.

Report the generated counterpart in the write effects. After serialization and
reparse, verify its presence, semantic membership, flat structure, and matching
Episode row IDs and positions. Ordinary missing or conflicting counterparts still
block additions; this decision does not infer or overwrite those relationships.

Unchanged drafts remain byte-exact. The established policy for creating an entire
missing dataset 2 remains unchanged, including SQLite targets that do not require
one.

## Consequences

Ordinary and Smart Playlist additions work with the evidenced layout while
producing paired Podcasts records. Existing flat and grouped records retain their
private metadata. Synthetic regressions cover absent and existing flat
counterparts, duplicate Episodes, metadata preservation, concurrent Podcast edits,
ordinary counterpart conflicts, and independently detected output corruption.
The supplied database is used only for private, in-memory verification; no user
data becomes a committed fixture.
