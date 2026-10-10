# ADR-0137: Warn and default unrecognized album collation

- Status: Accepted
- Date: 2026-10-09
- Amends: ADR-0021 for retained sort-36 collation differences

## Context

A second user's database reproduces the sort-36 rejection with a different retained
album order. Device, writer, and locale differences are possible; its last writer
is unknown. Requiring a captured comparison profile to explain every album prevents
otherwise valid additions from reaching a Prepared Library. The product owner chose
to accept a changed album browsing order and continue Sync with a warning.

## Decision

When album sort values change, use the first profile matching the complete retained
sort-36 group order. If none matches, use an explicit default: punctuation retained,
literal explicit sort overrides, leading `The` ignored in display-name fallbacks,
empty albums last, and compilations without Album Artist or Sort Album Artist last.
Emit `library.album_index` at warning severity for each affected Master Playlist
index. The warning explains that a default was used and album browsing order may
change. This policy does not claim to reproduce the source writer's collation.

Unchanged group sort values retain their source order. No-op preparation remains
byte-exact. Structural checks still require valid occurrence permutations,
contiguous album groups, and valid native representatives. Independent verification
checks the regenerated order against the same selected or default profile, along
with membership, disc/track order, retained ties, and trailing data.

## Consequences

Unrecognized collation alone no longer blocks Library preparation or Sync. Existing
supported orders retain their profile selection. The regression suite uses fabricated
fixture data; full-source checks remain read-only and keep candidate bytes in memory.
Physical device behavior and the exact user Sync draft were not replayed.
