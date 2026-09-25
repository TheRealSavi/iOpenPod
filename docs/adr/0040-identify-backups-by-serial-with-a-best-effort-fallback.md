# ADR-0040: Identify backups by serial with a best-effort fallback

- Status: Accepted
- Date: 2026-09-13
- Supersedes: ADR-0039's exact hardware-identity requirement
- Extends: ADR-0011 and ADR-0039

## Context

ADR-0039 required an exact, hardware-derived Device Identity before a native Backup
Snapshot could safely participate in restore. That model is stricter and more
complicated than the product needs. Users expect an iPod's serial number to associate
its backups, and the absence of a readable serial should not make backup or restore
unavailable.

## Decision

Backup format v4 Snapshots use a versioned Backup Identifier. The Application Layer
includes every known product and transport serial plus the current Volume Identity,
and the archive stores only domain-separated hashes of those values. Product serial
drives a new Archive Key when available, then transport serial, then Volume Identity.

Matching is serial-first. When both identifiers contain a serial, at least one
same-kind serial must match and a shared Volume Identity cannot override a serial
mismatch. When either side has no serial, matching falls back to Volume Identity.
This fallback is best effort: reformatting the iPod or observing it through a Host
that supplies a different Volume Identity can lose the association, and duplicated
Volume Identities can associate the wrong device. Missing serial evidence does not
otherwise block capture, retention, a pre-restore Safety Snapshot, restore, or
Restore Recovery. Existing restore validation, verification, journaling, and forced
Safety Snapshot requirements remain unchanged.

Original iOpenPod archive identifiers retain their separate Legacy Backup Import
rules. An explicitly unstable Original snapshot still cannot authorize restore.

## Consequences

The common path is understandable: backups follow the iPod serial number. iPods
whose serial cannot be read remain usable through the best identifier currently
available instead of entering a special no-restore archive. The application must
continue retaining the Volume fallback beside serial evidence so an archive created
before its serial became readable can still be recognized. The fallback provides
continuity, not a guarantee, and the GUI must not describe it as a stable Device
Identity.
