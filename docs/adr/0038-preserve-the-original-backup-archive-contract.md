# ADR-0038: Preserve the Original backup archive contract

- Status: Superseded by ADR-0039
- Date: 2026-09-12
- Extends: ADR-0005, ADR-0011, ADR-0014, and ADR-0029

iOpenPod 2.0 reads Original iOpenPod version-2 and version-3 Backup Snapshot
manifests, including legacy per-device blobs, and writes version-3 manifests over
the same shared content-addressed Host blob layout. This preserves existing user
archives without making the Original project a runtime dependency. New incompatible
formats require an explicit migration design rather than silently stranding older
snapshots.

The Application Layer owns the archive format and workflow, while all device access
crosses an identity-bound Storage Filesystem Session. Snapshot capture verifies every
copied file and rejects a source tree that changes during capture. Restore requires
the archive's stable hardware-derived Device Identity to match the Active iPod,
validates all referenced blobs before changing the device, creates a forced safety
checkpoint, uses fingerprint-checked writes and recoverable trash, and verifies and
flushes the final tree. Invalid manifests remain visible but cannot authorize
restore, export, deletion, retention cleanup, or blob garbage collection.
Participating processes serialize all repository access through a Host-side lease;
failed captures remove unpublished blobs, while the newest five automatic
pre-restore safety checkpoints remain outside ordinary snapshot retention.

Backup Snapshots remain user-controlled protection, not a substitute for Storage
Transactions or their recovery journals. The pre-Sync preference may create a
snapshot automatically, ask the user, or proceed without one; a requested snapshot
failure stops that save attempt, while choosing Off does not weaken the reviewed
write's own validation, verification, and recovery requirements.
