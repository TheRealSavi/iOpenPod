# ADR-0178: Generate basic Genius during Sync

- Status: Accepted
- Date: 2026-10-24
- Extends: ADR-0076, ADR-0176, and ADR-0177

## Context

The native Genius codecs and browser support experiments and retention, but normal
Sync does not generate relationship data. Classic preparation also requires root
`Extras.itdb` bytes that the application has not captured or published. The user
requests automatic, basic Genius readiness for all music on supported iPods during
Sync, without new Genius playback or collection-management controls.

## Decision

Sync carries explicit Genius regeneration intent when Device Registry confirms
native Genius Playlist support. The shared preparation workflow computes the graph
from the completed desired Library after media preparation and metadata policy.
This includes retained and successfully added music Tracks, excludes removed and
nonmusic Tracks, and also runs for Refresh Library without media changes. Ordinary
Library saves preserve existing Genius data instead of rebuilding recommendations.

A pure Application Layer generator owns recommendation policy. It reuses unique
retained Genius IDs and allocates deterministic, collision-checked IDs for other
music Tracks. Candidate lists use bounded metadata neighborhoods and a Library-wide
ring fallback, avoiding an all-to-all graph. Version 1 uses at most 256 candidates
per Track, a proven compact configuration without filtering rules, and the observed
25 desired / 10 minimum results. Every eligible Track receives metadata and a
candidate row; a small Library cannot be promised native playback merely because
its graph is structurally valid. No new dependency or network service is required.

The generator consumes the public `iPodDB.library.genius` contract, which exposes
typed graph intent and the compact configuration constructor alongside native
collection browsing. Application consumers do not import the payload codecs or
SQLite implementation modules directly.

Graph replacement and Mix replacement are distinct explicit intents. A Genius
update with `mixes=None` preserves existing native Mix containers and prunes their
unavailable starting Tracks. An explicit tuple replaces the Mix set; an empty tuple
clears it. Automatic Sync uses preservation and creates no Mixes or saved Genius
Playlists. Canonical Genius Playlists and saved sidecars retain their existing
protection and supported-remapping boundaries.

For non-SQLite targets, the application captures root `Extras.itdb` through Storage
when preparation requires Genius relationships, including an absence precondition
for creation. It supplies these bytes to iPodDB and includes changed prepared Extras
in the same reviewed, verified, recoverable transaction as iTunesDB. Ordinary Track
removal or replacement also captures the companion when retained Genius identities
need pruning. Late devices continue publishing the complete SQLite artifact set.
Present unreadable companions block writes instead of being replaced by empty data.

Sync source validation runs before staging and again before publication, including
Host and device evidence for duplicate-song matches. Automatic Genius writes must
not bypass the matching checks previously used by an unchanged Library save.

Explicit nonempty generation can initialize a missing Classic dataset-9 CUID using
the shared MHSD definition and the 32-byte ASCII hexadecimal shape from the working
hardware experiment. Its value is stable across repeated preparation of the same
source. Existing CUID data remains opaque and byte-exact; ordinary no-op, empty
updates, and SQLite updates do not initialize this record. The necessity of CUID
on every firmware is not established.

## Consequences

Supported-device Sync now deliberately regenerates the known Genius graph for the
resulting music Library. Repeated generation preserves Track Genius identities and
existing Mix identities. Unknown unrelated database data remains retained under
the existing iPodDB contracts. Recommendation quality and firmware usability are
separate from structural validation; complete physical lifecycle testing remains
necessary. Native Mix creation, Host Genius playback, and saved Genius Playlist
editing are outside this change.

Validation covers generation, cancellation, capability gating, complete app Sync,
companion capture and mutation checks, publication and recovery, and preservation
of existing native collections. Private device captures remain outside Git.
