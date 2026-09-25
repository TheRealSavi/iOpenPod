# ADR-0062: Assign matched Original backups to native identities

- Status: Accepted
- Date: 2026-09-17
- Extends: ADR-0039 and ADR-0040
- Supersedes: ADR-0040's separate-identity treatment for Original archives whose
  serial key matches the Active iPod

## Context

Original iOpenPod used a sanitized device serial as its per-device archive directory
key. Legacy Backup Import previously converted every such archive into a separate
`legacy--…` Archive Key with no native Backup Identifier. When that Original serial
also identified the Active iPod, the Backups page therefore showed the same connected
iPod twice: once for native snapshots and once for imported snapshots.

The legacy directory key alone does not say whether it represents a product serial or
a transport serial, and an explicitly unstable Original manifest must continue to
fail closed. Import also must not persist the raw serial in the v4 repository.

## Decision

`BackupService` may assign an Original archive to the Active iPod only when the
archive's non-reversible legacy identity claim matches one of the claims derived from
that iPod's currently observed product or transport serial. The assignment carries
the Active iPod's complete Backup Identifier and its resolved native Archive Key; the
repository does not infer an identifier kind from the Original directory name.

A matched Original snapshot that is not explicitly unstable is published as a
natively identified v4 snapshot in that Archive Key. Its hashed Original identity
claim and `legacy_source` record remain in the manifest as import provenance, while
the Original source archive remains unchanged. Reimporting a source snapshot that was
previously published under a separate legacy Archive Key first publishes and verifies
the assigned manifest, then removes the superseded converted manifest. Shared content
objects remain content-addressed and are collected only by the existing repository
rules.

An import without a matching Active iPod remains a legacy snapshot and keeps its
explicit per-restore confirmation requirement. An Original manifest marked unstable
is never promoted, even if its directory key happens to match current serial
evidence.

## Consequences

Native and matched Original Backup Snapshots for one iPod occupy one sidebar archive
and use one Backup Identifier. A repeated import repairs repositories created by the
older split behavior. Because the assignment comes from current typed Device
Evidence, import does not guess whether an opaque legacy key is a product or transport
serial and does not store the raw value.

Matched imports can use ordinary native restore authorization. Unmatched and
explicitly unstable imports preserve the stricter Legacy Backup Import behavior. A
process interruption between publishing the assigned manifest and removing the
superseded one can temporarily leave both copies visible; repeating the same import
is the bounded reconciliation path.
