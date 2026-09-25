# ADR-0024: Reconcile and verify Playlists by dataset

- Status: Accepted
- Date: 2026-09-05
- Extends: ADR-0021 and ADR-0022

## Context

The initial semantic writer preserved ordinary edits but could prepare incomplete
dataset mirrors, flat episodes in an empty Podcasts playlist, and new Playlists
without their extended identities. Verification through the Library Snapshot alone
could not detect these omissions because the projection hides firmware structures.
Original iOpenPod's writer and playlist dataset research provide the baseline.

## Decision

The public Library Draft remains source-bound and independent of native Chunks.
Private bindings and checks include dataset origin. Equal Playlist IDs in datasets
2, 3, and 5 do not by themselves establish interchangeable records.

An edit affecting playlist or browse relationships supplies dataset 2 when the
source has only dataset 3. The new companion retains source Playlist metadata and
uses flat MHIPs, with separate occurrence identities. Its Master contains the
library Tracks. Existing counterpart datasets retain their own records and private
metadata. Empty Master-only datasets can establish a mirror; additions to conflicting
or incomplete existing counterparts block preparation. Dataset 3 precedes dataset 2
after affected edits. A dataset-2-only source never acquires dataset 3 implicitly.

New Playlists receive matching primary and extended IDs, the database ID reference,
matching timestamp fields, and the standard opaque MHOD 100 display preferences
captured from Original iOpenPod. The shared definition-driven writer remains the
only serializer. Newly constructed playlist datasets receive a Master first;
new or structurally edited Masters receive missing standard browse index pairs.
Missing, repeated, or displaced existing Masters block dependent edits instead of
being automatically replaced. Unrelated edits retain source anomalies with warnings.

Podcast grouping applies only to the special podcast-marked Playlist in dataset 3.
The first episode creates its show group. Grouping retains native metadata and
stable duplicate occurrences; ambiguous retained ownership blocks the change.
Episodes are grouped by album in first-appearance order. When that changes the
submitted order, the Prepared Library exposes the resulting order with a warning.
Renaming preserves different flat and grouped orders already present in established
podcast counterparts.

Changes to the set or library order of podcast Tracks update the special Playlist's
membership, retaining surviving occurrences. When needed, an established dataset 3
permits creation of the special Podcasts playlist. Without that source evidence,
creating it is blocked rather than guessing target capability. This is explicit
firmware relationship maintenance, not general Smart Playlist reevaluation. An
untouched draft never triggers it. Derived membership changes accompany preparation
diagnostics and appear in the resulting snapshot.

Dataset 5 stays a separate firmware category universe. Its category flags, rules,
settings, and parsed membership remain retained; it is excluded from visible folder,
podcast, and Master-index reconciliation. Track deletion removes its dangling Track
occurrences while retaining category metadata. No category regeneration, relocation,
or unsupported rule evaluation is inferred from UI omissions.

Verification inspects reparsed native output in addition to the resulting Library
Snapshot. It checks counterpart presence and values, new native identities, Master
structure and changed membership, podcast group ownership and positions, folder
rules and aggregates, preorder, index ranges, and firmware dataset preservation.
Blocking diagnostics withhold the whole candidate. The application continues to
prepare in the background and save only the exact review it issued through Storage.

## Consequences

Application callers do not reproduce firmware rules or manipulate native datasets.
Source anomalies and unsupported relationships remain inspectable through structured
diagnostics. The writer can create supported structures while retaining the exact
no-op contract and avoiding destructive source repair.

Tests include fixed Original writer bytes, corrupted output injection, empty mirrors,
dataset identity collisions, category preservation, duplicate episodes, malformed
Masters, automatic podcast membership, and large Playlist batches. These establish
format and workflow evidence; they do not claim physical firmware testing.
