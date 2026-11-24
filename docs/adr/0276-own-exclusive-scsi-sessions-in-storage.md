# ADR-0276: Own exclusive SCSI Sessions in Storage

- Status: Accepted
- Date: 2026-11-17

## Context

Classic firmware update research needs native SCSI transfers. Filesystem Sessions
and the existing read-only Hardware Probe do not authorize vendor data-out
commands. The inspected family-33 firmware advances its upload cursor after a
failed transfer and its completion handler is not safe to repeat. A general
transport retry or automatic eject on cleanup could therefore corrupt an update
or boot an incomplete image.

## Decision

Storage owns a separate **SCSI Session**, bound to one Mounted Volume and
Connection Generation. It accepts typed, bounded commands and contains no iPod
update codec. The Application Layer retains package qualification, protocol
policy, recovery planning, progress journaling, and post-install verification.

The initial Windows adapter opens the retained Volume GUID, verifies the physical
disk number and exact INQUIRY vendor, product, and unit serial, and obtains an
exclusive Windows volume lock. It checks identity again after locking and holds
that same native handle until close. It honors native transfer and alignment
limits. It never falls back to a reassigned drive letter, forcibly dismounts a
busy volume, or takes over another application's open files.

Storage requires existing sessions on that Physical Device to close first,
reserves access against new local sessions, and retains the shared Host Volume
writer lease. The native lock protects the selected Volume, not every other
Volume a Physical Device might expose. Firmware qualification must separately
account for disk layout and any additional Volumes.

Commands are serialized. Any failed command, failed status, or unexpected
transfer length invalidates the connection and closes access; no retry occurs.
Only explicitly requested data-in commands may accept short replies. Closing
releases resources without issuing an eject, reset, or protocol finalizer.

## Consequences

Lock failure is a busy-device result, not a reason to weaken exclusivity. Windows
flushes cached filesystem writes when acquiring the lock. Other native adapters
report this capability as unsupported until independently implemented.

The transport is not an installer and does not establish rollback safety. Device
Summary remains download-only. The family-33 hardware qualification now includes
exclusive access, standard reads, and one complete stock 2.0.1 vendor upload.
Normal boot, independent full-span firmware comparison, and unchanged library
databases were observed afterwards. This does not qualify interrupted-upload
recovery or a different model.
See [Classic update research](../research/classic-stock-update-source-path-2026-11-17.md).

The Windows behavior follows
[volume locking](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_lock_volume),
[SCSI pass-through](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddscsi/ni-ntddscsi-ioctl_scsi_pass_through_direct),
and [adapter transfer limits](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddstor/ns-ntddstor-_storage_adapter_descriptor).

## Native macOS and Linux updates, 2026-11-24

For normal-mode firmware updates, verify the selected disk and the SCSI vendor,
product and unit serial before publishing any firmware bytes. macOS matches
the USB transport serial and mounted partition to one IOKit service, retains its
interface, unmounts the selected partition normally and obtains exclusive access
before checking SCSI identity. Linux binds the partition and SCSI generic node
to one kernel disk sequence, checks SCSI identity, unmounts only that partition
through UDisks2 and retains an exclusive whole-disk descriptor alongside the SCSI
descriptor. It checks identity again after locking. Desktop authorization can
grant a descriptor for that USB connection. Commands run in the user process.

Busy volumes and failed identity checks stop the operation. The installer uses
its existing pinned image and command journal on every Host. Native updates
on macOS and Linux still require physical acceptance testing.
[Apple SCSI exclusive access](https://developer.apple.com/documentation/iokit/scsitaskdeviceinterface/1575374-obtainexclusiveaccess)
and [UDisks2 block access](https://storaged.org/doc/udisks2-api/latest/gdbus-org.freedesktop.UDisks2.Block.html).
