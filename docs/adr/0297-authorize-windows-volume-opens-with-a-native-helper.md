# ADR-0297: Authorize Windows Volume opens with a native helper

- Status: Accepted
- Date: 2026-11-24
- Extends: ADR-0276 and ADR-0296 for standalone Windows distribution

## Decision

When the initial read/write open of the selected Volume GUID fails with access
denied, Storage requests one UAC authorization. A small native helper opens that
exact Volume, verifies its disk number and USB bus, and duplicates the handle
into the normal application process. Other open errors stop without prompting.
The Application Layer and GUI remain ordinary-user processes. The helper accepts
no firmware, SCSI command, arbitrary filename, executable or driver-install request.

The parent retains all existing disk and exact SCSI identity checks, adapter
limits, exclusive Volume locking and connection validation before firmware
transfers. The helper closes its original handle before returning. Failed locking,
identity checks or transfers never cause another authorization or command replay.
This preserves the same file object and access rights across authorization.
Microsoft documents non-administrator pass-through with a read/write handle;
its FAT implementation records Volume-management access when opening the Volume.
See [DuplicateHandle](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle),
[SCSI pass-through](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddscsi/ni-ntddscsi-ioctl_scsi_pass_through),
[FAT open](https://github.com/microsoft/Windows-driver-samples/blob/d49bb7d72f3651952b2b6e4ad28d14fe2247eb69/filesys/fastfat/create.c#L2497-L2526)
and [FAT lock](https://github.com/microsoft/Windows-driver-samples/blob/d49bb7d72f3651952b2b6e4ad28d14fe2247eb69/filesys/fastfat/fsctrl.c#L3246-L3291).

## Distribution and authorization boundary

Compile the helper on the Windows builder with MSVC, a static C runtime and
system-only dependent DLL resolution. Verify its x64 architecture, DLL imports
and load flags during building and when inspecting the frozen archive. Embed it
and its SHA-256 in the single-file download; the digest is frozen Python code,
not a writable sidecar beside the extracted helper. Users need no compiler,
Python installation or Visual C++ redistributable for this helper.

Do not elevate the PyInstaller onefile application: its documentation warns
against that use. Stage the verified native helper in a private directory with
administrator read/execute access, including when UAC uses another administrator
account. Pin the directory against replacement and the file against writing and
replacement throughout launch and handoff. The native helper imports only
Kernel32 and Advapi32. Its manifest is `asInvoker`; only explicit `runas` elevates
it. See [PyInstaller's warning](https://pyinstaller.org/en/stable/operating-mode.html#how-the-one-file-program-works)
and [dependent DLL flags](https://learn.microsoft.com/en-us/cpp/build/reference/dependentloadflag?view=msvc-170).

The parent creates a random, single-instance, local-only named pipe, with an
explicit administrator/System ACL. It retains the launched process and checks
the pipe client's exact PID before sending readiness. The helper uses
identification-only security quality of service, matches the server PID and
retained parent creation time, and checks that parent is alive. Overlapped I/O
has bounded waits. Cancellation aborts pending I/O before releasing its buffers.
No credentials or executable code cross the pipe.

The parent accepts a complete fixed-size reply only after helper exit success.
Before publishing a reply, helper failure revokes its tentative duplicate.
After publication the helper never closes the parent's handle. An abrupt crash
between duplication and publication can leave an unused handle until application
exit; this is not a crash-atomic transaction. No firmware command or Volume lock
has occurred at that point. Physical acceptance must still verify the actual
device/filesystem/filter stack and UAC credential paths.

## Validation and consequences

The native helper's diagnostic mode exercises real pipe authentication, process
identity, message framing and exit handling without elevation or device access.
Every frozen Windows smoke check runs this mode after hash verification. Tests
cover access-denied-only authorization, cancellation, timeout, wrong peers,
failed helper exit, changed payloads, identity checks and Volume locking.

The release builder now needs Visual Studio C++ Build Tools and the Windows SDK;
the existing Windows CI image supplies them. This is a build-time requirement,
not a new application dependency. Signing identities remain release credentials.
When signing is used, sign this helper before computing its embedded digest and
signing the outer executable. Unsigned candidates can be rejected by an
administrator's signed-executable policy.

DFU still follows ADR-0296: bundled libusb, then the installed Apple driver on
Windows. UAC Volume access does not install a missing DFU driver.
