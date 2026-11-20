# ADR-0282: Install shared Classic firmware from Device Summary

- Status: Accepted
- Date: 2026-11-17
- Supersedes: ADR-0281's offline OS installation boundary and experimental UI notice
- Packaging and stock offers superseded by: [ADR-0283](0283-bundle-universal-classic-firmware-and-remove-stock-offers.md)
- Identity selection and evidence presentation superseded by: [ADR-0284](0284-separate-reported-firmware-from-hardware-and-bootloader-evidence.md)
- Completion policy superseded by the 2026-11-19 amendment below.

## Completion amendment, 2026-11-19

The project owner requested removal of the post-update Check installation and
About confirmation steps. Acknowledgement of all upload and finalizer commands,
followed by the restart request, now completes the installation. A missing USB
response to that final restart also completes the upload, retaining the pending
restart command and logging the missing reply. Explicit failed responses,
incomplete transfers and Host journal failures continue to surface as errors.

Completion records the acknowledged upload. Current firmware, bootloader and
Library observations continue to describe only evidence actually collected.
The completion dialog shows the uploaded version and asks the user to let the
iPod restart. It offers Close immediately.

Older awaiting-boot, reboot-in-flight and boot-verified records with a fully
acknowledged upload are completed from their Host receipts during startup or
before a later installation. This migration preserves the original version,
hashes and any saved observations. Interrupted records retain their error state.
The existing pre-write qualification and command journaling still govern uploads.

## Earlier decisions

Device Summary exposes two separate Windows workflows: **Unlock bootloader**
installs the shared 2.0.0 loader through DFU, then **Install iOpenPod firmware**
installs Apple 2.0.5 with Mod Platform Version 0.2.0-dev through normal USB. Restore
iPod and Update iPod retain their stock-package download behavior. Enable all four
Classic updater families (24, 33, 35 and 38) by explicit project-owner direction.
The shared pair has physically booted only on family 33; the other families use
the binary comparisons, native execution and simulated transport evidence.

Ship the exact device-independent common OS as a compressed application asset.
Fetch the pinned Apple family-38 IPSW for its resource bank, then compose and
validate the complete image against the physically tested release hash. Retain
both the download and prepared image in persistent Host application data. A
valid prepared cache works offline. Users need neither an ARM compiler nor a
sibling research checkout. The roughly 3.9 MB compressed asset contains
Apple-derived executable code; its notice explicitly excludes that code from
iOpenPod's GPL grant. This replaces the earlier patch-only distribution boundary
for this OS asset; personalized loader headers remain local.

Require a verified shared-loader receipt for the same serial, model and hardware
family on this Host before enabling installation. Normal USB cannot inspect NOR;
the receipt records the previous verified unlock, not a fresh measurement of the
installed loader. An external stock restore invalidates that assumption: run
Unlock bootloader again. A different Host likewise verifies the loader through
DFU once. Routine OS updates then need no DFU or per-device OS signature.

The Application Layer retires the selected Filesystem Session and reserves the
device while a worker owns preparation, upload and verification. Storage alone
opens retained device handles and executes commands. Before writing, validate the
live identity, normal-mode status, qualified running release, actual firmware
capacity and transfer bounds; record visible layout and library hashes without
creating another device backup. Observe connection generation changes throughout.

Journal each command intent before execution and acknowledgement afterward. Once
the first update command begins, cancellation cannot interrupt the sequence and
closing the dialog cannot detach the writer. Never retry an uncertain command.
An unfinished receipt survives app restart and exposes a read-only result check;
an incomplete upload requires separate DFU recovery, not an automatic replay.
After fresh discovery, verify the selected device's running 2.0.5, unchanged
visible disk layout and library, then safely eject it. The user confirms both
About versions before the installation record becomes complete. This is not an
independent full firmware-partition readback or a power-loss recovery guarantee.

The 2026-11-18 restart-response amendment distinguishes an acknowledged upload
from an acknowledged restart. If only the final restart command raises a SCSI
command error with no valid response, keep the durable `reboot-in-flight` intent
and show **Firmware uploaded**, with instructions to check after normal boot.
Record the underlying error in the Host log. Do not retry the command, invent an
acknowledgement, or mark the installation complete. The same read-only result
check and About confirmation remain required. Reopening the flow retains this
presentation from the saved intent. Upload/finalizer failures, explicit failed
SCSI responses and Host journal failures remain errors. Storage still invalidates
and closes every failed SCSI Session; this is Application Layer interpretation,
not a transport retry or an exception to Storage safety. The user reported a
successful 0.6.3-dev update alongside Windows error 121; its completed receipt
records all 3,111 upload commands. Tests inject a missing restart reply to cover
that plausible timing without claiming the original USB exchange was captured.

The later 2026-11-18 verification amendment separates firmware completion from
the Library preservation observation. A real 0.6.4-diag receipt had all upload
commands acknowledged, and its connected iPod reported that exact Mod Platform
Version with unchanged disk layout. Its iTunesDB hash had changed while the
other captured Library files matched. Treating any hash difference as a hard
firmware failure trapped subsequent installations behind **Check installation**.

Continue requiring a fully acknowledged upload, the same selected device/Volume,
normal boot, sufficient capacity and unchanged visible disk layout. When a
qualified current Bootloader Report names the receipt's exact Mod Platform
Version, complete that receipt directly through the USB check. Compare against
the saved upload version, not a newer bundled release. A present invalid report
or a version mismatch fails; absence retains the legacy safe-eject/About route.
This uses the running firmware's report, not cryptographic attestation or a full
firmware-partition readback. No command is replayed.

Retain the original Library hashes and a separate verified Library observation.
Changed files do not prove that the firmware write damaged them: normal use and
later Sync operations may occur before the result check. Display that preservation
could not be confirmed without claiming an unchanged Library or blocking a
verified firmware result. Unreadable music-library files still fail the check.
The Host receipt records the reported mod version and both Library observations;
old receipts without those optional fields remain readable. Current report-based
checks leave the iPod connected, so users can proceed to the newer bundled release.
The legacy manual About flow carries the same Library notice through completion.

The common OS reports updater family 38 on older Classic hardware. Device
Registry therefore resolves an exact observed 38/2.0.5 to the 2.0.5 firmware
contracts while retaining the Device Profile's physical generation. Missing or
conflicting firmware evidence still prevents qualification.

See [the physical trial](../research/classic-shared-205-os-layout-2026-11-17.md#physical-family-33-trial),
[the runtime workflow](../firmware-mods.md) and
[release packaging](../../scripts/firmware/README.md).
