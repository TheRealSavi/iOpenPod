# ADR-0252: Reinspect legacy Host Tracks for native ratings

- Status: Accepted
- Date: 2026-11-10
- Extends: ADR-0063, ADR-0099, and ADR-0168

## Context

Native file ratings now enter the common Track through the shared tag reader. Host
Media Scan Cache v16 and earlier can hold completed Track metadata from a parser
that omitted these ratings. An unchanged source matches the cache indefinitely,
leaving its rating at zero even after the reader gains support. Cached tag values
have no marker that distinguishes an absent native rating from a parser omission.

## Decision

Host Media Scan Cache v17 accepts supported v9-v16 documents, validates their
records, and marks decoded Track metadata incomplete. Each unchanged Track is
reinspected once and written back with the current native rating interpretation.
A matching cached Acoustic Fingerprint or confirmed no-audio result can still be
used during that inspection. Valid Photo, folder artwork, and eligible Playlist
records retain their existing reuse and migration rules. Current v17 records
remain reusable without reinspection. The cache remains disposable and read-only
with respect to selected Host media.

This is a targeted exception to ADR-0168's reuse of older media records. It does
not change cache schema fields or add a dependency.

## Consequences

The first scan after upgrading may open every unchanged Track once and spend more
time on metadata inspection. Later scans reuse the refreshed v17 records. Existing
Acoustic Fingerprints avoid repeated audio analysis where source facts still
match. Previously cached Photos, folder artwork, and eligible Playlists do not pay
for the native rating migration.

This record preserves the original uncommitted workstation migration decision.
Its original ADR number was reassigned to fit the current upstream sequence.
