# ADR-0146: Remove routine Podcast and re-encoding notices

- Status: Accepted
- Date: 2026-10-15
- Partially supersedes: [ADR-0024](0024-reconcile-and-verify-playlists-by-dataset.md)

Routine Podcast Playlist membership maintenance and show grouping no longer create
informational diagnostics. This supersedes ADR-0024's requirement to report those
changes; the Prepared Library still contains and verifies the resulting membership
and order. The shared media transcoder also stops generating the generic notice
that re-encoding a lossy source can reduce audio quality, for both Podcast and Host
media preparation.

These notices describe expected work and add noise to Sync results. Their producers
are removed entirely, with no presentation filter or ignored-message list. Other
media adjustments, validation failures, and recovery diagnostics continue through
the existing reporting paths.
