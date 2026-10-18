# ADR-0147: Restore late-iPod firmware write compatibility

> ADR-0150 amends refresh to retain existing SQLite schemas, version rows, and
> unrepresented metadata while applying the checked CDB projection.

- Status: Accepted
- Date: 2026-10-16
- Amends: ADR-0033, ADR-0061, and ADR-0141

## Context

Nano 6 users report that the latest 1.x release boots after Sync while 2.x does
not. Differential execution against Original iOpenPod branch `1.x`, commit
`a20242428`, found firmware-facing differences that schema and integrity tests
did not catch. Some were accepted without a physical firmware check. Same-input
HASHAB and Locations checksum-book generation already match Original.

Ordinary in-memory SQLite serialization leaves file change counters and the last
writer version zero. Original's file writer populates them. SQLite accepts both
forms, so this difference alone does not establish the boot-failure cause.
Original also uses small positive browse-group IDs, zero references for absent
artists/composers, no partial store records, and filetype-based AAC classification.

ADR-0033's statement that Original creates ArtworkDB with root value 6 and a
type-6 MHAF child is incorrect for this 1.x baseline. Actual Nano 6 publication
uses root value 2 and no auxiliary MHAF child. The Nano 5/7 captures cited by that
ADR are separate evidence. Existing captured roots and Unknown Data must still
be retained.

Finally, replacing the generator cannot repair previous output when a no-change
Sync never regenerates the SQLite Library Artifact Set.

## Decision

SQLite generation uses SQLite's private memory-file backend to obtain ordinary
file-header semantics without filesystem persistence. Complete generation,
postprocessing, validation, signing, and publication retain their existing
boundaries. No hand-authored header patch or new dependency is introduced.

Browse groups use Original's positive sequential identity policy, independently
of retained CDB identities. Absent artist/composer names have zero references.
Track and user Playlist persistent identities remain authoritative; native smart
rules and folder links must retain their valid references. Dates alone do not
authorize creation of a partial `store_info` row. An AAC purchase flag alone does
not change a normal AAC file into a Purchased AAC location. Actual protected-file
and codec evidence remain represented. Ordinary containers write zero for the
checked-only flag when no Smart Playlist preferences are present.

The Nano 6 Device Profile explicitly selects ArtworkDB creation root 2 and omits
auxiliary image records when creating new ArtworkDB or PhotosDB image records.
Other profiles retain their existing evidence-based policy. The Application Layer
carries this creation capability into iPodDB; iPodDB does not branch on model
names. Existing roots, auxiliary records, and Unknown Data remain unchanged by
this creation policy.

An explicit SQLite-regeneration intent can accompany a Library Draft. A
user-directed Sync on a SQLite-capable iPod requests that intent even when its
Track, Playlist, and Photo state is unchanged. Preparation preserves unchanged
CDB bytes while independently verifying their projection and replacing all six
SQLite artifacts through the usual reviewed Storage Transaction. Existing
artifact fingerprints and signing identity remain publication preconditions.
Discovery, selection, ordinary no-op serialization, and unrelated default no-op
drafts do not acquire this write intent.

When a reviewed Sync has no selected changes, the GUI exposes this operation as
**Refresh Library** for SQLite-capable iPods. Controller and executor admission
use the same capability; preparation and publication keep their normal checks.

## Consequences

Compatibility fixes reach existing SQLite installations through a no-change Sync.
The complete replacement still requires signing evidence and may fail safely
before publication. Sync performs additional SQLite preparation and writes even
when no media changes are selected.

The fix does not restore every historical 1.x omission. Valid user Playlists,
chapter bytes, native sample counts, date conversion, copyright, media flags,
and tested sorting remain represented. Original's M4B-to-MP3 fallback is not
copied. Image fitting and original Photo retention also remain unchanged.
Consequently, arbitrary complete 1.x and 2.x outputs are not byte-identical.

Regression fixtures and differential probes establish the repaired contracts.
They do not establish resolution of the physical Nano 6 boot failure. Retained
ArtworkDB roots are not rewritten based only on a value shared by valid captures
and previously generated files.
