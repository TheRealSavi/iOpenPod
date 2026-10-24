# ADR-0186: Reconcile Genius collections after Track removal

- Status: Accepted
- Date: 2026-10-24
- Extends: ADR-0176, ADR-0177, ADR-0178, ADR-0184, and ADR-0185
- Supersedes: Their seed-deletion and saved-sidecar remapping restrictions

## Context

Track actions are now available in the Genius browser. A member deletion must
preserve the rest of its collections, including native Playlists and saved plist
representations. The former policy blocked deletion of a known Playlist seed and
any change to existing Track positions while saved sidecars were present. Mix
membership was pruned but an entirely depleted container remained.

Original iOpenPod's `origin/1.x` Genius writer creates empty tables and supplies no
collection-reconciliation policy. The current typed seed and sidecar codecs provide
the format knowledge needed for a bounded extension of the existing save workflow.

## Decision

Metadata edits preserve collection membership, identity, name, order, duplicate
occurrences, ownership, and age. They do not reclassify saved collections from genre
tags or regenerate their membership. Sync and Refresh Library continue to rebuild
Genius relationships from the resulting music Library. Media replacement retains
the existing invalidation of old graph references and unavailable Mix candidates.

Explicit Track deletion removes only occurrences of the deleted Tracks. A known
Genius Playlist seed that is deleted becomes the first surviving member in native
Playlist order. This changes only the understood MHOD 54 seed field; retained Smart
data, seed headers, occurrence metadata, and Unknown Data remain preserved. Arbitrary
seed and membership edits remain rejected. An unknown seed remains opaque.

A collection made empty by Track deletion is removed. Unaffected collections,
including preexisting empty ones, are retained. Empty canonical Playlists are omitted from
the authorized draft, matching saved sidecars are recoverably removed, and empty
SQLite Mix containers and dependent rows are omitted. Matching Mix ownership is
removed in the same transaction. This does not change the automatic Count; a later
Sync can fill a vacated slot. Graph refresh or media replacement alone does not
delete a retained Mix just because it temporarily has no assigned starting Tracks.

Capture saved sidecars with their file preconditions before preparation. Reconcile
them against the final prepared Library's persistent identities and physical Track
order, after identity allocation. Preserve surviving occurrence order and duplicates;
update Classic positions together with their persistent IDs. Nano identity-only
documents keep their absent position array. A deleted seed uses the matching
canonical Playlist's repaired seed, when available, otherwise the first surviving
sidecar member. Names, timestamps, saved indexes, Playlist identities, format, and
unknown plist values remain unchanged. Unchanged output is byte-exact.

Unsupported or malformed affected sidecars and opaque graph references continue
to block unsafe dependent changes. Unchanged and append-only Track order can
preserve such sidecars without interpreting them. No guessed offsets, timestamps,
or identities are introduced.

Database output, remapped sidecars, collection removals, ownership changes, and
graph pruning share the existing validated and recoverable Storage transaction.
Changes to captured inputs invalidate the review before publication. Preparation
does not mutate device files, and backup settings are not a prerequisite.

## Consequences

Ordinary member and seed deletion no longer requires the user to delete a surviving
Genius Playlist. Structural repair preserves the remaining saved selection; choosing
a replacement seed does not claim to reproduce Apple's original recommendation
choice. No new dependency is introduced. Synthetic and virtual-device tests cover
reconciliation, Unknown Data retention, source changes, and recovery. Physical
firmware acceptance of replacement seeds and remapped saved sidecars remains open.
