# ADR-0176: Preserve and author native Genius data

- Status: Accepted
- Date: 2026-10-24
- Extends: ADR-0100, ADR-0141, ADR-0150, and ADR-0175

## Context

Physical experiments established native Genius Playlist playback on Classic 6.5G
and Genius Mix playback on nano 7G. Original iOpenPod's empty Genius tables are a
compatibility baseline, not a complete implementation. SQLite regeneration retained
graph tables but discarded SQLite-only Mix containers and membership. Fresh captures
also contain saved Playlist variants with positional and persistent-ID references,
or persistent IDs alone.

## Decision

Keep recommendation policy outside iPodDB. Pure `iPodDB.genius` codecs model bounded
configuration, metadata keys, and candidate lists. Unsupported versions, compressed
lists, and unknown instructions remain explicit opaque payloads. Understood edits
preserve suffixes; malformed known framing fails. Dataset-9 CUID remains opaque.

Typed SQLite Genius documents retain source bytes, schemas, unknown tables and
columns, with exact unchanged serialization. Explicit updates replace known graph
data. Ordinary writes preserve it, pruning understood relationships when Tracks
are removed or their media is replaced. Opaque candidate data blocks dependent
pruning instead of being guessed or discarded.

Library Drafts accept explicit Genius updates independently of Library Snapshots.
Preparation coordinates MHIT Genius IDs with Classic root `Extras.itdb`, or with
the complete late-device SQLite artifact set. Short Track IDs, persistent Track
IDs, and Genius IDs stay separate. Existing Classic Genius identity changes require
captured companion bytes to retain unrelated data. All prepared companions belong
to one Storage publication; iPodDB never opens or writes device paths.

SQLite-only kind-32 Mix containers, ordered seed candidates, UI state, and seed rows
survive regeneration. Inspection and explicit authoring do not make SQLite another
semantic Library authority. Mixes are not ordinary fixed Playlists. Application
callers supply the selected Device Registry capabilities.

Saved Genius Playlist documents belong to `iPodDB.sidecars`. Preserve raw timestamps
without assuming their epoch. Preserve unknown plist values and exact unchanged
bytes, including future versions. Explicit remapping validates persistent IDs and
any positions; removing the seed fails. Capture does not import or consume these
files. The application preservation path currently accepts unchanged/append-only
Track order and blocks other changes until explicit remapping is integrated.

## Consequences

This supersedes ADR-0141's empty-only Genius authoring policy and closes ADR-0150's
Mix preservation gap. There is no new dependency, recommendation service, GUI, or
automatic generation policy. Missing layouts and unproven formats remain explicit
limitations. Callers publish prepared artifacts together through Storage, retaining
recovery and unchanged-input checks. See [the API contract](../ipod-genius.md).
