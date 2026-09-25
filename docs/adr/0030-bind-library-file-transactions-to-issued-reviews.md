# ADR-0030: Bind Library file transactions to issued reviews

- Status: Accepted
- Date: 2026-09-11
- Extends: ADR-0021, ADR-0023, ADR-0026 and ADR-0029

Artwork selection and Track removal require dependent file changes beyond iTunesDB.
The Library Workspace now retains bounded artwork pixels and explicit omission
intent with the same draft revision as metadata and Playlists. Removing a Track
filters its Playlist occurrences; resetting or loading the workspace clears assets
and deletion intent. The metadata editor still cannot edit native or media facts.

The application captures required thumbnail inventories, eligible source prefixes,
and removed media fingerprints through Storage. Files referenced by surviving
Tracks remain. Missing removed media stays absent, with that absence rechecked.
Media removal is restricted to validated paths beneath `iPod_Control/Music`.
Opaque artwork IDs and captured bytes are passed to iPodDB for pure preparation;
the application does not parse or reconstruct native database records itself.

After independent verification, the coordinator constructs and validates one
immutable Storage Transaction: thumbnail writes, changed ArtworkDB, iTunesDB, then
recoverable media removals. The exact issued Library Review privately owns that
transaction. Public file descriptions expose paths, actions, sizes, and hashes for
review and inspection but confer no write authority. A later preparation supersedes
an older attempt even if the older one finishes last. New saves use transaction
journals; existing single-file recovery journals remain supported by Storage.

Save rechecks source databases, signing identity, and required playback-sidecar
inventory at the final preparation boundary. Cancellation and connection checks
remain inexpensive during streaming. Only verified success adopts the transaction's
observed fingerprints and resulting Library, clears the draft, and invalidates the
thumbnail cache. Interrupted publication retains the journal and invalidates save
authority; reconnecting does not revive an old review.

Independent artwork verification preserves existing image ranges and source image
sizes, checks complete retained file prefixes against captured SHA-256 values, and
rejects duplicate output paths or overwriting uncaptured retained thumbnails.
Source artifacts supply these expectations independently of reconciliation.

This enables artwork changes and Track removal through application requests, with
Clear Artwork and Remove from Library actions in shared context menus. A cover file
picker, incoming-media inspection/import/replacement, recovery UI, sidecar
reconciliation, and unsupported database/signature variants remain unfinished.
Artwork capture currently retains at most 512 MiB of eligible thumbnail prefixes;
large-file streaming at the iPodDB resource boundary remains further work.
