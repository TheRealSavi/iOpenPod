# ADR-0278: Allow Host-built unsigned custom firmware

- Status: Accepted
- Date: 2026-11-17
- Extends: ADR-0275, ADR-0277

The user wants subsequent Firmware Mod builds and updates to work without DFU
or per-device signing. After the initial bootloader installation, the custom
loader will accept an explicitly identified unsigned OS image format. Image
framing, target identity, length bounds, actual read counts and an unkeyed
checksum remain mandatory. These checks detect malformed or damaged images;
they do not establish authorship or restrict users to project-approved builds.

The immutable BootROM still authenticates the installed bootloader. This decision
changes the loader's policy for the OS it loads, retaining the original signed
Apple path and the earlier device-authenticated custom path. Initial installation
and recovery may still require DFU; routine custom OS composition and upload must
not require the device's hardware key.

The first implementation is scoped to the exact Classic33 Apple 2.0.1 target.
Bootloader and image formats require compiled-code tests and physical acceptance;
source analysis alone does not establish installation readiness. Device mutations
stay in Storage, and Device Summary remains download-only during qualification.
