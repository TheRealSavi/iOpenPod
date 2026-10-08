# ADR-0128: Discard explicitly removed Track media after Library save

- Status: Accepted
- Date: 2026-10-08
- Amends: ADR-0029 and ADR-0030 for ordinary Remove from Library actions

## Context

An ordinary Library Draft that removes hundreds of Tracks previously fingerprinted
every obsolete media file repeatedly before a recoverable Storage Transaction.
Reading each complete file from the iPod dominated preparation time. The user chose
permanent deletion for this action and does not require recovery of those media
files.

## Decision

For ordinary Remove from Library saves without incoming media, the Application
Layer captures each obsolete Track file's cheap filesystem identity through
Storage. It does not hash or stage that media for transaction recovery. Files still
referenced by surviving Tracks remain untouched. Missing files remain absent.
Changed identities block the save before publication.

The reviewed Storage Transaction publishes and verifies database, artwork, sidecar,
and other writes as before. After commit, the Application Layer finalizes that
transaction's recovery namespace, then asks Storage to delete the unchanged
obsolete Track files permanently. Storage validates the Device Path, regular-file
type, filesystem identity, and active Filesystem Session before each deletion.
After the batch, Storage flushes the Volume; an unconfirmed flush reports safe-eject
guidance.
The review labels these effects as permanent deletions and displays sizes without
claiming a content hash.

If transaction cleanup fails, Track files remain and the saved Library reports a
warning. If a file changes or deletion fails after commit, Storage leaves that file
in place and the saved Library reports the incomplete deletion. An interruption may
leave unreferenced media on the iPod; it never restores a Library that refers to
already deleted media. The user can recover removed media only from an independent
Backup Snapshot, if one exists. Sync, media replacement, Photo deletion, and other
transaction removals keep their existing recovery contract.

## Consequences

Ordinary bulk Track deletion avoids full media-file reads during preparation and
does not consume recovery space for the deleted files. The database remains verified
and recoverable until its transaction is finalized. Permanent deletion has no
automatic rollback or retry after a partial post-commit failure; the warning makes
remaining files explicit.
