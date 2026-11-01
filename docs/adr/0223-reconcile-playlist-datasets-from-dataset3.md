# ADR-0223: Reconcile Playlist datasets from dataset 3

- Status: Accepted
- Date: 2026-11-01
- Amends: ADR-0024, ADR-0174, and ADR-0213 for counterpart authority and repair

## Context

[Issue 301](https://github.com/TheRealSavi/iOpenPod/issues/301) reports that adding a
Playlist on an iPod nano 4 fails with `playlist.ambiguous_mirror`, while existing
Smart Playlists remain editable. Synthetic sources reproduce this distinction:
additions required agreement across the entire dataset. Original iOpenPod's
dataset research and `_playlist_builder` preserve separately supplied lists.
The maintainer has explicitly chosen one output policy: dataset 2 must agree
with authoritative dataset 3. Disagreement is repairable state rather than a
reason to block an otherwise valid Library write.

## Decision

Whenever both datasets exist, reconcile dataset 2 from dataset 3 before resolving
requested edits and again after native editing. Create missing rows, correct
conflicting rows, remove dataset-2-only rows, and follow dataset 3's Playlist order.
This includes Masters, ordinary and Smart Playlists, folders, Podcasts, and Genius
Playlists. Duplicate or malformed dataset-2 structures are replaced from the
unambiguous dataset-3 authority. Invalid authoritative data, unsupported signing,
and Storage safety still use ordinary validation.

Logical identities, names, definitions, kinds, parent links, sorting, markers,
and ordered Track occurrences must agree. Compare native Smart definitions even
when their rules cannot be projected semantically. Dataset 3 retains Podcast
show groups; dataset 2 contains the same ordered Episodes without groups or group
references. Known dataset-3 occurrence positions prevail; missing position
evidence can retain a counterpart value for ordinary Podcast repair.

Matching rows retain their private data. Surviving occurrences in corrected rows
retain their own metadata and persistent identities, matched by Track and
occurrence order; new occurrences receive fresh identities. Conflicting
Playlist-level records use dataset 3's retained representation, including Unknown
Data. Dataset-2-only records disappear from the candidate. The captured original
remains retained through normal recoverable publication. Dataset 5 is unchanged.

Record repair in the Library change list and Review effects even without other
edits. Ordinary saves, Sync, and selection-time preparation share this policy.
Automatic Smart Playlist evaluation remains enabled. Additions, nested Playlist
references, combined edits, and folder changes have no counterpart exception.

Reparsed output must satisfy the counterpart contract. Native verification uses
the reconciled baseline for replaced dataset-2 records and retains normal checks
for dataset 3 and unrelated data. Repeating preparation does not repeat repairs.
Pure parse/serialize remains byte-exact; preparing divergent data repairs it.
Whole-dataset creation retains the existing device policy: affected dataset-3-only
binary Libraries gain dataset 2; SQLite targets may omit it, and dataset-2-only
Libraries do not acquire dataset 3 implicitly.

## Consequences and validation

Counterpart differences no longer prevent adding or editing Playlists. Dataset 3
is the explicit authority, so data found only in dataset 2 is removed from the
prepared Library rather than merged into the visible Library. Recovery retains
the original database.

Tests cover missing, conflicting, extra, duplicated, and reordered rows;
repair-only preparation; additions, edits, nested references, and folders;
Podcast flattening and occurrence preservation; idempotence; source retention;
corrupted-output rejection; and virtual-device publication. The report has no
database attachment, so its exact differences and physical firmware acceptance
remain unverified.
