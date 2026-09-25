# ADR-0011: Bind Storage access to Connection Generations

- Status: Accepted
- Date: 2026-08-28

## Context

A Mount Point is a temporary Host path. It can disappear, be reused for a different
Volume, or refer to a reconnected Physical Device after an operation has already
retained it. Passing ordinary `Path` values around the application would make it
possible to escape an authorized device root or mutate a replacement Volume through
stale state.

The Original iOpenPod contains valuable path-containment, filesystem-profile,
durability, capacity, writer-lock, and safe-eject research. Those protections are
spread across application and device modules, however, and some workflows still
perform filesystem mutations directly. Reusing that arrangement would violate the
Storage boundary accepted in ADR-0002.

Cross-platform filesystem behavior also differs for reasons that are real rather
than architectural. Windows exposes Volume GUIDs and Win32 storage calls, macOS
exposes `diskutil` and Disk Arbitration concepts, and Linux exposes a block-device
and mount hierarchy. The rest of iOpenPod should not need to branch on those Host
details.

## Decision

Storage is the sole device-facing filesystem portal and has two public depths:

1. `Storage` discovers or inspects mounted Volumes and creates Filesystem Sessions.
2. A `FilesystemSession` performs controlled operations within one authorized
   Volume root.

The following rules apply:

- Storage keeps Physical Device Identity, Volume Identity, Mount Point, and
  Connection Generation as separate typed concepts. A discovered Mount Point alone
  never authorizes access.
- A Filesystem Session is bound to the complete observed connection, its filesystem
  type and capabilities, and a process-local Connection Generation. Storage
  reinspects that connection around operations. A disconnect, identity change,
  remount, filesystem change, or loss of required access permanently invalidates
  every sibling session from that generation.
- Device-facing APIs accept `DevicePath`, a normalized relative value that rejects
  absolute paths, traversal, ambiguous components, NULs, and drive prefixes.
  Storage checks every existing component for symbolic links or reparse points
  before access. Explicit Host-to-device or device-to-Host copies use `HostPath` so
  the boundary crossing is visible in the call.
- The platform seam is internal. Native adapters own mounted-volume discovery,
  identity and capability observations, reinspection, and filesystem flushing. A
  virtual adapter backed by an ordinary temporary directory is the deterministic
  verification environment; it is not a mock of a second architecture.
- A write is create-only by default. Replacing or moving an existing file requires
  the exact `FileFingerprint` returned by a prior Storage read. There is no
  unconditional-overwrite operation.
- Single-file writes and Host imports stage a unique sibling file, check filesystem
  size and free-space limits, flush staged bytes, revalidate the connection and
  precondition, atomically replace, flush directory metadata where the Host permits,
  and verify the committed content hash.
- Participating writers serialize through a Host-side per-Volume lease. Storage does
  not create a lock file on the device merely to coordinate writers.
- Removal is recoverable through `trash()` and `restore_trash()`. The foundational
  interface exposes no permanent-delete operation.
- Storage remains generic. It imports no iOpenPod, Device Registry, iPodDB, database,
  media, or GUI knowledge. Ordinary application settings, logs, caches, Backup
  Snapshots, and temporary files remain iOpenPod responsibilities.

The first implementation provides snapshot discovery and safe single-file
operations. Multi-file Storage Transactions, durable Operation Journals,
event-driven native connection monitoring, and safe native eject remain required
Storage work before Sync or destructive maintenance workflows are enabled. The
Application Layer must not reproduce those missing capabilities by sequencing raw
filesystem calls itself.

## Consequences

Device access now has one typed, testable route on Windows, macOS, and Linux. Most
safety behavior is verified against virtual Volumes, while small native adapters can
be tested from captured platform observations. Replacing discovery mechanisms later
does not change application filesystem calls.

Callers must retain `MountedVolume` and fingerprint values supplied by Storage and
must open a new session after reconnection. A user-selected Host path does not become
a Device Path, and a Device Path cannot be passed to ordinary Host filesystem APIs
outside Storage.

Fingerprint preconditions prevent silent lost updates but do not make a group of
file changes atomic. Sync must wait for the transaction and journal layer rather
than treating several successful `FilesystemSession` calls as a committed unit.
Snapshot discovery also requires explicit refreshes until native lifecycle
subscriptions are implemented.
