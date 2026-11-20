# ADR-0281: Share Classic OS and bootloader artifacts

- Status: Accepted
- Date: 2026-11-17
- Supersedes: ADR-0280's separate output bundles; retains exact source qualification
- Installation boundary superseded by: [ADR-0282](0282-install-shared-classic-firmware-from-device-summary.md)

Use one Apple 2.0.5-derived OS and one bootloader executable for Classic updater
families 24, 33, 35 and 38. Different source deltas reconstruct the same loader
body; they are migration encodings, not per-family builds. iOpenPod obtains the
two BootROM authentication values from the destination iPod during initial DFU
installation. Only those header values differ by device. Subsequent OS builds
use unkeyed framing and CRC checks, with no per-device signing.

The shared loader reads real SysCfg at every boot. Its SoftwareVersion policy
accepts the four known hardware revisions and retains the family-24 stock
version range. After successful validation of a shared OS, it changes only two
words in the copied OS handoff: compatibility hardware revision and loader
version. Original SysCfg, native driver configuration, serial, model and region
remain intact. Stock and legacy custom handoffs retain their original values.
Normal-mode updater-family observations can therefore describe the common OS;
the installer resolves actual hardware independently in DFU.

The common OS uses schema 2 and target `CLSC`, preserving schema-1 migration
support in the shared loader. Compose the whole latest firmware-member layout,
including its resources, instead of squeezing the OS into older slots. Mark
Apple's AUPD already applied so it cannot replace the custom loader. The
normal-update transport must preserve the device-specific hash record; identical
OS artifacts do not imply identical installed partition bytes. Require actual
firmware-partition capacity before any future installation workflow.

The Windows unlock action now installs or upgrades to the shared loader. Old
handoff receipts remain result-check-only, and existing recovery copies are
reused. All four targets are experimental for this new executable. Offline
native execution, binary audits and simulated installation do not establish
physical boot, USB return or interruption recovery. OS composition is offline;
Restore and Update remain download-only. See the
[boot-context evidence](../research/classic-shared-205-boot-context-2026-11-17.md)
and [OS layout evidence](../research/classic-shared-205-os-layout-2026-11-17.md).
