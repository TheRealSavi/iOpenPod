# ADR-0287: Report measured Classic bootloader through current USB

- Status: Accepted
- Date: 2026-11-18
- Supersedes: ADR-0284's lack of a normal-USB bootloader report and mandatory
  same-Host DFU receipt for every compatible firmware update

Add an optional **Bootloader Report** Firmware Mod to the shared Classic OS.
Measure the actual plaintext NOR loader once in the relocated bootstrap, before
Apple's OS entry and task/driver initialization. Publish the retained result in
a nested `iOpenPodBootReport` dictionary through Apple's existing SysInfo VPD XML
writer. Reading during startup avoids borrowing the SPI controller from a running
driver. USB serialization performs no hardware reads or additional polling.

The bounded reader uses only NOR Read and Read Status commands, restores controller
configuration and interrupt masks, and fails explicitly on busy, encrypted,
unrecognized or unreadable input. It streams the full executable through SHA-256
and retains the Bootloader Identity Record plus SysCfg serial, model and hardware
revision. It neither decrypts OEM code nor exposes device keys. Bootloader 2.1.0
and the existing USB transport remain unchanged.

The Application Layer owns the typed parser and compatibility decision. Accept
only the current connection's XML, bind its identity to the selected iPod and
require both the complete qualified executable hash and the matching marker.
This permits routine updates on another Host without recreating a DFU receipt.
Current invalid, failed or incompatible reports override historical receipts;
only an entirely absent report permits the legacy receipt migration path. Recheck
inside the retained Storage SCSI Session before issuing any update command.

Device Summary says **Reported by firmware**, while the legacy fallback says
**Last verified in DFU**. This is a boot-time measurement supplied by the running
firmware, not cryptographic attestation or a continuously refreshed flash reading.
The report does not authorize firmware by itself, identify arbitrary encrypted
OEM versions, or replace the explicit first-install DFU workflow.

The 0.6.0-dev release includes this mod. Native emulation covers all four hardware
families and the actual Apple XML writer; physical validation remains outstanding.
See [implementation evidence](../research/classic-bootloader-report-2026-11-18.md).
