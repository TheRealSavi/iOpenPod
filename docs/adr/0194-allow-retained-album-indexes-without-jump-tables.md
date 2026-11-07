# ADR-0194: Allow retained Album indexes without jump tables

- Status: Accepted
- Date: 2026-10-26
- Amends: ADR-0148's retained index/jump-table pair requirement

An Album refresh rejected a supplied Library whose two Master Playlists each
contained all 1,915 Tracks exactly once and one complete sort-4 MHOD 52 index,
but no MHOD 53 jump table. The independently confirmed working Apple/Finder
mini 2 capture also has indexes without jump tables; see the
[capture comparison](../research/mini2-finder-comparison-2026-10-22.md#playlists-browse-indexes-and-ordering).
Original iOpenPod creates pairs when authoring new indexes, but that creation
policy does not establish a requirement for retained sources.

Explicit Album refresh accepts exactly one retained sort-4 index with zero or
one matching jump table. It preserves the absence of a jump table and rebuilds
one when present. Duplicate indexes, duplicate jump tables, orphan jump tables,
and incomplete or repeated Master occurrences still block dependent refreshes.
Diagnostics distinguish invalid index structure from ambiguous membership.
Sources with neither record remain unchanged during refresh alone. Structural
edits retain their existing index-creation and membership-reconciliation policy.

Independent verification still checks index permutation, Album contiguity,
ordering, retained record counts, and Master occurrences. Existing jump tables
must still cover the regenerated order. No-op preparation, unrelated records,
and Unknown Data retain their preservation contracts. No application or Storage
boundary changes are needed; Sync continues to request the same explicit refresh.

Fabricated regressions cover index-only reordering, both dataset copies, source
ambiguities, corrupted output, and signed virtual-device Sync. The supplied source
also passes pure refresh preparation without diagnostics or any byte changes.
This establishes Host-side preparation and virtual publication; physical firmware
acceptance and the reporter's complete Sync remain separate evidence.
