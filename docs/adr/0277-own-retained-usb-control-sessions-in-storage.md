# ADR-0277: Own retained USB Control Sessions in Storage

- Status: Accepted
- Date: 2026-11-17

## Context

The user has authorized a modified Classic firmware and the bootloader changes
needed to load it. BootROM DFU exposes no Mounted Volume, so the SCSI Session
cannot carry this installation. Persistent device mutations still belong in
Storage. Research DFU tools establish protocol behavior but must not become an
alternative application write path outside that boundary.

## Decision

Storage owns a separate USB Control Session for one observed native interface.
It carries bounded USB setup requests and immutable output bytes, retains the
same handles, serializes requests, and invalidates itself on transfer failure.
It does not retry, reconnect, reset, eject, or finalize a device protocol on
close. Each open receives a new Connection Generation. The Application Layer
owns firmware qualification, device identity checks on that held session,
image authentication, progress journals, installation policy and verification.

The initial Windows adapter implements the installed driver's PIPE0 framing.
It re-enumerates the complete interface path and instance identity before and
after opening, including the driver's optional hub/mux path. It requests
nonshared handles and never falls back to a different path or access mode.
Overlapped buffers remain alive until completion, including cancellation after
timeouts or interruptions. A Host writer lease serializes cooperating Storage
clients. The portal prevents its filesystem and SCSI sessions from overlapping
USB control access; the caller closes earlier access before changing modes.

## Consequences and qualification limits

The connected Classic's Apple DFU driver accepts a second open even when the
first requested share mode zero. **The native driver does not provide an
exclusive lock.** The Host lease therefore protects participating Storage
clients, not arbitrary external USB tools. Qualification runs one controller
process at a time, with other DFU/install tools closed. This limitation must not
be presented as the exclusive-volume guarantee of ADR-0276.

Read-only hardware qualification currently includes discovering the exact
interface, opening retained handles, obtaining GETSTATE=2, and observing the
driver's sharing limitation. Automated tests cover transfer bounds, session
invalidation, cancellation lifetime, identity changes and no shared-access
fallback. The research workflow subsequently qualified full BootROM/SysCfg reads,
two NOR-helper dry runs and a one-use persistent bootloader installation through
this transport, with independent full NOR readback and normal stock boot.
No firmware installer is attached to Device Summary by this decision. See the
[physical boot-path evidence](../research/classic33-modified-boot-path-2026-11-17.md).

The packet layout follows the pinned Rockbox and Reprise transport sources.
Handle and buffer lifetime follows Microsoft's
[overlapped completion documentation](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-getoverlappedresult)
and [WriteFile requirements](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-writefile).
