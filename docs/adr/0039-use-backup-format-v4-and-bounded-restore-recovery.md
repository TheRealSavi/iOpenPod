# ADR-0039: Use backup format v4 and bounded restore recovery

- Status: Superseded by ADR-0040
- Date: 2026-09-12
- Supersedes: ADR-0038
- Extends: ADR-0011, ADR-0014, and ADR-0029

## Context

Original iOpenPod version-2 and version-3 archives conflate a filesystem-safe
directory name with device authorization and encode each file as one slash-delimited
string. Continuing to write that format would preserve ambiguities that iOpenPod 2.0
can avoid. A conventional self-contained Storage Transaction is also unsuitable for
whole-device restore because retaining every original and staging every replacement
on the iPod can require nearly twice the device's capacity.

## Decision

iOpenPod 2.0 owns Backup Archive format v4, continuing the format-version sequence
after the Original iOpenPod v2 and v3 formats. V4 manifests use exact path
components, immutable content identities, checksummed catalogs, and
versioned hardware-derived identity claims. An Archive Key locates an archive but
never authorizes restore. Hardware serials, legacy device keys, and Host volume
identifiers are not stored in v4 manifests or directory names; domain-separated
SHA-256 claims support matching without retaining those raw identifiers. New archives
need not be readable by Original iOpenPod.

Capture performs one Device content read for each new or changed file. Storage hashes
the source while streaming it to a staged Host file and rejects a file whose size or
filesystem identity changes during that stream. The repository verifies and publishes
the resulting content-addressed Host object, then performs a metadata-only rescan of
the Device tree before publishing the manifest. It does not rehash the complete Device
after copying.

An ordinary capture may reuse content from the latest snapshot when canonical path,
size, and modified time match and the existing Host object remains a safe regular file
of the expected size. A forced pre-restore Safety Snapshot never uses this shortcut.
Restore and export deeply verify every referenced Host object before consuming it.
This policy deliberately treats full Device rehashing and repeated Host-object
scrubbing as separate integrity work instead of blocking every capture.

Original version-2 and version-3 archives enter the v4 repository only through an
explicit, read-only Legacy Backup Import. Import validates every manifest and blob,
copies verified content, and records the source identity assertion without modifying
the Original archive. Historical metadata such as Original's `pre_sync` reason is
normalized for display only and does not attach Backup to the new Sync workflow. An
imported snapshot that cannot prove an exact Device Identity
requires a stable connected iPod, a matching legacy key, and explicit confirmation
for each destructive restore. An explicitly unstable Original snapshot cannot
authorize restore.

Restore first creates and verifies a forced Host safety snapshot. Storage then executes
one journaled transaction while retaining the Volume writer lease, staging at most one
replacement file on the iPod at a time. The Operation Journal uses the safety snapshot
as verified recovery material instead of duplicating the complete original tree on the
iPod. Recovery therefore requires the same Host repository. Backup locations on any
Volume of the same Physical Device are rejected.

Catalog and recovery-record reads and writes are size-bounded, reject ambiguous JSON
such as duplicate fields and malformed Unicode, and require the exact v4 schema.
Storage-owned recovery, trash, and `.iop-*` staging
namespaces are outside the Backup Snapshot file-tree scope, so interrupted internal
work cannot become restorable user content.

Restore terminal states are typed. Completion implies final content, metadata, and a
successful durability barrier. A verified already-current result means no device
write was attempted. Pre-mutation failure, cancellation, incomplete publication, and
durability pending remain distinct. An unresolved restore pins its
safety snapshot and blocks its deletion or note mutation, as well as further backup
restore mutations, until recovery succeeds or the device reconnects and the user runs
Restore Recovery. Recovery verifies and
finalizes a committed target, or rolls an incomplete publication back to the verified
safety snapshot. The GUI keeps that required action visible and presents typed,
actionable errors instead of raw exception text.

## Consequences

Backup format v4 need not preserve write compatibility with Original iOpenPod, but
the Legacy Backup Import becomes a permanent compatibility obligation. A future
incompatible archive change advances the shared lineage to a later backup format
version rather than starting a separate native version sequence.
Archive decoding, migration, corruption handling, identity authorization, and path
validation remain hidden behind the backup module's interface. Storage gains bounded
external-recovery transactions without learning about iPods or Backup Snapshots. The
backup and restore workflow remains independent of Sync and other product workflows.
Incremental reuse cannot detect a same-size Device file changed while preserving its
exact modified time, and capture does not discover latent same-size Host bit rot.
Those limits are explicit: iOpenPod prevents its own concurrent Device writes, the
final metadata rescan catches ordinary external changes, and every restore or export
still fails closed on a full Host-object hash mismatch.
