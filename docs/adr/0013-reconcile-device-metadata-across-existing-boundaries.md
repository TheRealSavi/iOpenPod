# ADR-0013: Reconcile device metadata across existing boundaries

- Status: Accepted
- Date: 2026-08-29

## Context

Real filesystem-accessible iPods may have missing or stale SysInfo and
SysInfoExtended files. Exact model identification can require current SCSI VPD
evidence that differs by Host: Windows provides SCSI pass-through, macOS provides
IOKit SCSITask, and Linux may require a root-time udev helper for VPD page 0x80. The
Original iOpenPod also introduced `iOpenPodSysInfoAuthority`, a version-1 JSON record
that tracks per-field provenance and hashes device metadata to detect external
changes.

Putting VPD plist parsing or model lookup in Storage would violate ADR-0002 and
ADR-0010. Letting Device Registry open paths would do the same. Writing during
discovery would mutate a device the user has not selected. Conversely, silently
trusting persisted authority as current hardware would promote cached evidence and
could preserve an incorrect model indefinitely.

The current Storage foundation has verified single-file atomic replacement but not
a general multi-file Storage Transaction. Metadata repair therefore needs a bounded,
idempotent recovery rule that does not weaken the transaction requirement for Sync
or destructive maintenance.

## Decision

Device metadata reconciliation crosses the existing boundaries without moving
their responsibilities:

- Storage revalidates the Connection Generation before a native hardware probe and
  returns generic `HardwareProbeObservation` values. They may contain standard SCSI
  identity, page-0x80 unit serial, vendor payload bytes, and opaque Host properties.
  Storage assigns no iPod meaning to those values.
- Windows uses SCSI pass-through, macOS uses IOKit SCSITask, and Linux uses SG_IO
  when accessible plus non-privileged udev properties. The shared VPD collector only
  understands SCSI framing. iOpenPod supplies the device-specific page-index plan;
  Storage executes that generic plan without assigning meaning to the returned
  bytes.
- The Application Layer translates Apple iPod observations into current Device
  Evidence. On Linux it recognizes the Application-owned product-serial property
  and asks the user to install the bundled least-privilege udev rule when needed.
  The rule reads VPD page 0x80 through `scsi_id`; it does not loosen block-device
  permissions.
- Device Registry owns a pure reconciliation function. Given ranked Device Evidence,
  an exact Device Profile, and already-read metadata bytes, it preserves unknown
  fields, lets current hardware correct stale device metadata, refreshes
  profile-derived cache fields, and returns desired SysInfo, SysInfoExtended, and
  authority bytes.
- The authority record remains version 1 and compatible with Original iOpenPod. It
  records per-field values, source names, evidence-authority names, update times,
  file metadata, and SHA-256 hashes. A matching authority record remains persisted
  device metadata; it is never manufactured into current-hardware evidence.
- Discovery performs no writes. After the user selects an exactly identified
  candidate, `DeviceCoordinator` analyzes the three files. If the Volume is safe for
  writes, it atomically publishes changed SysInfo and SysInfoExtended bytes, then
  publishes authority last, reads all three back, and flushes the Volume. If the
  Volume is read-only, selection may continue with a structured repair-skipped issue.
- A failed or interrupted prefix cannot appear committed because the authority
  hashes will be absent or stale. The next selection replans from the observed bytes.
  This narrow metadata-cache workflow does not authorize Sync, database mutation,
  deletion, or any other multi-file workflow.

## Consequences

Missing metadata can be created and stale metadata can be corrected without making
Storage know about iPods or making Device Registry perform I/O. Captured VPD bytes,
authority documents, and virtual Volumes provide deterministic tests on every Host.
Linux users may need one explicit setup step, but iOpenPod does not request broad
raw-disk permissions.

Selection can perform a small write before the Library loads, so it must retain the
same Connection Generation checks, preconditions, verification, flush reporting,
and disconnect behavior as other device operations. Three atomic files are not a
general transaction: a process or hardware failure can leave an incomplete prefix,
which is detected and repaired on the next pass rather than rolled back. Sync and
destructive workflows still require Storage Transactions and durable Operation
Journals.
