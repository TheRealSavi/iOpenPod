# ADR-0152: Normalize Podcast Sync to the 12.6 baseline structure

> ADR-0153 extends the shared relationship policy to SQLite Sync, with a separate
> traversal policy based on the Nano 5 capture.

- Status: Accepted
- Date: 2026-10-19
- Amends: ADR-0149 and ADR-0148 for explicit non-SQLite Sync

## Context

An incoming iPod may have either the supplied 12.6 Baseline structure or the
Classic 6.5 structure. The requested Sync outcome is the baseline's structural
relationships, regardless of which input was loaded. Preserving all untouched
source anomalies, Title sorting, and retained positions under ADR-0149 cannot
produce that outcome. Episode content, literal identities, and database versions
are not the target of this normalization.

## Decision

Non-SQLite Sync containing Podcasts submits explicit `normalize_podcasts=True`
intent to iPodDB. Loading and ordinary no-op preparation remain lossless. The
ordinary `repair_podcast_links` behavior remains available independently.

The explicit policy applies to retained and newly added Episodes:

- Each unambiguous show has one native album row, with its name and available
  feed URL, Podcast content type, and a representative Track persistent identity.
  Referenced duplicates and unreferenced name-only shadow rows are merged.
  Existing canonical identities survive. Private bytes and metadata survive;
  conflicting retained data blocks preparation. Mixed ownership and different
  feeds sharing the same native show name are not guessed through.
- The special Podcasts Playlists use Release Date sort 24 and the observed
  `0x10B` low phase/flag bits, retaining unrelated higher bits. Grouped rows have
  increasing row IDs, valid Episode parent references, and a persistent identity
  per show. Matching flat and grouped Episode positions equal their row IDs.
  Missing group opaque words receive the observed creation seed `0x8001`;
  existing nonzero values, including `0x8101`, survive without inferred semantics.
- Podcast Tracks and both special Playlist counterparts reference the retained
  root secondary database identity. A missing root identity is allocated locally;
  identities from the reference capture are never copied. Older Track headers are
  not expanded solely for this relationship.
- Master sort-36 indexes containing Podcasts are repaired even when their dependencies otherwise
  appear unchanged, and created when absent. Shows remain contiguous, Episodes
  traverse newest publication first, absent dates follow dated Episodes, and
  retained order resolves ties. Unchanged non-Podcast traversal is retained.
  An incomplete source Master with no Podcast occurrences remains covered by the
  existing source warning; this policy does not invent missing Master membership.
- Missing native covers can be recovered from retained embedded media through a
  Storage capture, without a feed refresh or a replacement download. Captured
  file fingerprints bind those pixels to preparation and publication. New and
  retained covers share the existing memory budget and ArtworkDB pipeline.

The application continues ADR-0151's audio Podcast media type 4 and playback
policy. Existing video classification, chapters, timed artwork, user state,
unrelated indexes, and Unknown Data remain supported. This decision does not
clone source database versions, platform fields, purchase/account metadata,
opaque Playlist payloads, or firmware files. Optional album datasets on older
devices remain optional. SQLite targets retain their existing workflow.

## Consequences

Sync now deliberately changes some previously retained native fields. Analysis
exposes that intent, and verification reparses the serialized output to check
album membership/backlinks, database references, group identities, counterpart
positions, Playlist settings, and traversal. Unsafe or ambiguous merges fail
before publication. Storage remains the only boundary that mutates device files.

Synthetic regression fixtures cover both input structures, missing indexes,
retained bad ordering, new Episodes, repeated normalization, private data, and
corrupted serialized output. Full application Sync is also exercised against
private virtual-device copies of both supplied captures. Those checks establish
the serialized structure and transaction behavior; physical firmware and Finder
acceptance remain separate device tests.
