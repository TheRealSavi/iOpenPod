# Shared Classic 2.0.5 boot context

Date: 2026-11-17. Scope: offline inspection and native emulation of the shared
Classic bootloader design. No USB interfaces or physical disks were opened.
This establishes specific compatibility gates and handoff behavior, not physical
startup or flash qualification on all four Classic generations.

Subsequent physical work installed this candidate and booted both the previous
2.0.1 OS and shared 2.0.5 OS on one family-33 MB565. See the
[physical trial](classic-shared-205-os-layout-2026-11-17.md#physical-family-33-trial)
for the observed results and remaining limits; the offline findings below retain
their original scope.

## Result

A shared executable can read each device's real identity from its existing
SysCfg at boot. The 2.0.5 SystemConfig module already does this; no per-device
identity needs to be embedded in the shared loader body. Two separate revision
checks prevent an unchanged latest loader and OS from being drop-in replacements:
the loader excludes revisions below `0x0200`, and OS startup excludes revisions
below `0x0300`. Merely relaxing the unsigned-image authentication gate does not
remove either check. [Native validation][native], [disassembly][version-asm],
[OS predicate][os-gate].

The implemented design can retain real SysCfg during native driver initialization,
accept the four known hardware revisions in SoftwareVersion, and canonicalize
only the copied boot context for the shared 2.0.5 OS immediately before handoff.
This follows RepriseOS's compatibility values without embedding RepriseOS's
per-device companion data in the common executable. Existing stock and earlier
custom images retain their original hardware context. [Upstream assembly][assembly],
[production bridge][bridge], [native production probe][production].

## Exact original inputs

The latest plaintext loader body is 129,024 bytes and has SHA-256
`d2670f7e5493c4b5ed4b9b6fa2029ce1e519c1927522384469e810fbf408fb5e`.
Relevant full PE module hashes are:

| Module | SHA-256 |
| --- | --- |
| SystemConfig | `21835d42d091e160adfc8b0e38e00ddc0ac4a149c517099efd8325a8b5a97f29` |
| SoftwareVersion | `ef780c54db62b6218ed48b4416a0d12f58ad3d3fcda280c612d96c177530a619` |
| Bds | `6f0989ec72cfc881b074ffa75da398896e2e7aca169948de68574d2898f01ab3` |

The local 2.0.5 logical decrypted OS body, without its `0x800`-byte IMG1 header,
is 10,632,448 bytes with SHA-256
`d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224`.
Its main runtime mapping is `raw_body_offset = runtime_address - 0x08000000 +
0xaf98`. Do not substitute the older 2.0.4 mapping in upstream `docs/osos.md`.
[Module receipt][modules], [local OS runtime map][runtime-map].

## Native identity construction

SystemConfig's Thumb function at PE offset `0x2f8` builds a zeroed `0x120`-byte
SysInfo from the SysCfg record array and record count. It publishes the pointer
and length in the protocol at module `0x7bc`. Its memory information comes from
the native memory map. The per-device fields include:

| SysInfo offset | SysCfg input |
| --- | --- |
| `0x18`, 16 bytes | `SrNm` |
| `0x38`, 8 bytes | `FwId` payload + 4 |
| `0x84`, 4 bytes | `HwVr` payload + 4 |
| `0x92`, 4 bytes | `Regn` payload + 4, when its format is 1 |
| `0x98`, 16 bytes | `Mod#` |
| `0x104`, 4 bytes | `Codc` |
| `0x108`, 16 bytes | `SwVr` |

SysInfo `+0x118` is the `vrsn` marker and `+0x11c` is the loader version.
For the latest loader the latter is `0x01808003`, loaded from module literal
`0x478`. Across the four original SystemConfig modules, the only pre-debug byte
differences are in that loader-version literal. It does not force every unit's
HwVr to the latest revision. [SystemConfig disassembly][system-asm],
[module comparison][modules], [native SysCfg cases][native].

Eight native cases execute this original builder for all four HwVr values and
two synthetic regions. Allocation, memory enumeration and BootServices memcpy
are mocks; the native tag dispatch and field copies execute unchanged. The
cases verify serial, firmware ID, model, hardware, codec, software version and
region preservation. No actual device identity is present in these fixtures.
[Probe source][probe], [native results][native].

## Loader compatibility check

Bds `+0x328` calls SoftwareVersion before reading the image header. Arguments
are `r0 = protocol`, `r1 = SysInfo HwVr`, `r2 = firmware-directory image version`.
Return is EFI status, with `0x80000003` indicating rejection. The latest
SoftwareVersion protocol callback pointer is at PE `0x504`, originally `0x221`;
the native checker occupies `0x220..0x241`, followed immediately by module entry
`0x242`. Its final debug section starts at `0x560`.
[Bds disassembly][bds-asm], [SoftwareVersion disassembly][version-asm].

The original latest checker requires:

- HwVr upper half equal to `0x13`;
- HwVr lower half at least `0x0200`;
- image version in `0x15000..0x15fff`.

The first-generation Classic's original checker instead accepts image versions
in `0x13000..0x13fff`. Therefore preserving family-24 stock fallback requires
retaining that version range as well as relaxing the revision restriction.
[Four-family disassembly][modules].

The common replacement accepts exactly `0x00130000`, `0x00130100`, `0x00130200`
and `0x00130300`. All four accept `0x15000..0x15fff`; only `0x00130000` also
accepts `0x13000..0x13fff`. Authentication and image framing remain separate
checks. Native emulation exercises 15,390 hardware/version combinations against
the original function and 46,170 against the final compiled replacement at three
relocation bases, including neighboring revisions, invalid low bytes and unsigned
underflow. The final test calls through the relocated protocol pointer.
[Replacement source][version-source], [native production results][production].

## OS compatibility check and conditional handoff

The actual 2.0.5 ARM predicate at `0x082b32e4` accepts only family `0x13` with
revision at least `0x0300`. Startup at `0x083899b8` reads the imported HwVr and
calls this predicate at `0x083899c0`. Failure selects the soft-update warm-boot
reason and resets. The predicate was executed for all four intended revisions
and a foreign family: only `0x00130300` passes. [Predicate disassembly][os-gate],
[startup disassembly][os-startup], [native results][native].

RepriseOS copies real identity fields into its companion, then overwrites SysInfo
`+0x84` with `0x00130300` and `+0x11c` with `0x01808003`. This is explicit
upstream source behavior, not proof that an unchanged latest stock loader boots
earlier Classics. Its NOR bootloader is Rockbox and its Apple startup companion
runs in RAM. [Pinned assembly][assembly], [pinned profile][apple-profile],
[upstream boot sequence][boot].

The native Bds path offers a narrower adaptation point:

1. At `+0x4b8`, load the SystemConfig protocol from original `SP+0x38`.
2. At `+0x4ba`, load its SysInfo pointer and size into `r1/r2`.
3. At `+0x4c4`, copy SysInfo to fixed IRAM address `0x22028cc0`.
4. Replace `+0x4c6..0x4c9`, original bytes `67 49 17 98`, with a Thumb call.
5. For the already-validated unsigned type `0x7f`, schema 2 and `CLSC` target,
   write compatibility values only at copied SysInfo `+0x84` and `+0x11c`.
6. Replay displaced `r1 = 0x2203ff18`, `r0 = [original SP+0x5c]`, then continue
   at native `+0x4ca`.

The original header remains available at `SP+0x20`. This path follows successful
body validation. It leaves the original SystemConfig allocation, actual NOR
SysCfg, serial, model, region, codec and memory information unchanged. Stock
images and schema-1 custom images bypass the compatibility rewrite. The
production bridge preserves `r2`, `r3` and the callee-saved registers. To stay
within Bds's original 128-byte debug section, its 24-byte stub calls a helper in
the ROM extension through the existing relocated header callback plus a compiled,
checked symbol displacement. It adds no protocol field or special validation
command. [Production bridge][bridge], [ROM helper][gate], [Bds disassembly][bds-asm].

Nine hundred native production cases execute the actual Bds copy and patched
handoff for four hardware values, five image types, three schemas and five
targets at each of three relocation bases. They assert the original source
remains unchanged, only the two intended words change for the common image, and
native boot-flag publication, stack, `r2/r3` and callee-saved registers survive.
The final ROM and Bds PE modules execute together. BootServices memcpy is mocked.
These cases do not boot the full operating system or exercise device drivers.
[Production probe][production-probe], [production results][production].

## Early loader layout constraints

Moving all FFS files after DxeMain is unsafe without further changes. The latest
SecCore startup reads body word `0x1f7c0`, value `0x22010545`, as its PreEfi entry
and branches there. PreEfi is uncompressed and has absolute in-place references.
The original PreEfi FFS starts at `0xe1d8`, with PE image base `0x2200e1f4`.
Growing an earlier compressed Bds FFS and shifting PreEfi would leave this entry
and its native references wrong. Preserve the early entry anchors and account
for increased compressed sizes explicitly; unchanged SecCore bytes alone do not
establish a valid boot path. [SecCore disassembly][seccore],
[upstream absolute startup bindings][bindings].

The final candidate preserves those anchors. Bds's compressed FFS grows by 16
bytes; the immediately following ImageManagerSecurity module contributes those
16 bytes by removing only debugger information. Its executable code, data and
relocation records remain unchanged, and its following boundary stays fixed.
Its base is zero, its relocation directory is `0x660` with 32 bytes, and its
`RELOCS_STRIPPED` flag is clear. The only raw PE changes are the debug directory
at `0x128..0x12f` and debugger payload at `0x680..0x71f`.
[Independent final audit][audit].

Independent Reprise extraction yields 41 executable modules in 42 FFS files.
ROM, Bds and SoftwareVersion carry the functional changes; ImageManagerSecurity
has only the debug removal above; the other 37 modules match their original
bytes. The full PreEfi FFS and SecCore tail match the originals. All FV/FFS header
checksums and enabled payload checksums pass. This audit also compares the
independently extracted replacements to the exact modules used by native tests.
[Audit source][audit-source], [audit results][audit].

The latest PreEfi pre-debug bytes match family 33 exactly. SystemConfig differs
only by loader version, but not every hardware driver is identical: the latest
ATA module differs from family 24/33 and matches family 35. The shared-loader
design therefore still requires physical validation of native device startup;
matching CPU and security interfaces is not a full driver compatibility test.
[Module comparison][modules].

## Reproduction and evidence limits

Research scripts and raw artifacts remain ignored in the sibling lab under
`artifacts/classic-shared-205-context-20261117`. `analyze_modules.py` pins Capstone
5.0.6. `probe_context.py` pins Unicorn 2.1.4 and Capstone 5.0.6;
`probe_shared_handoff.py` pins Unicorn 2.1.4. Run through UV. The final production
receipt refers to the common candidate with unmarked body SHA-256
`6dcd77343c06621bbd58a2db62ccb74dbd6aeaa6f11eac2d36fc8f3e96573e80` and modules:

- SoftwareVersion: `cd7f714e494743242dd79411594ae3a42907529636471b0f7665c2cbcec578d0`;
- Bds: `a8a038cb29ce801678e0b35312f795d033587fe3ba72d7effd3358127f11e22f`;
- ROM: `ba5ca3b5cc7e3734f0b790feaab7d43df4109cb1c4a8c6dc608878a6a3f31246`.

The separately added identity record and packaged writer subsequently passed
bundle validation recorded in `scripts/bootloader/README.md`. The offline tests
in this report do not establish physical
flash success, power-loss recovery, full 2.0.5 startup, or stock fallback on an
earlier Classic. Upstream source revision is osos-lab
`d2c8e357d58591bdaa70bb6be9da191f489554a6`.

[assembly]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-bundle/src/assembly.rs
[apple-profile]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/firmware/apple.json
[boot]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/docs/boot.md
[bindings]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/loader/apple/nor/bindings.h
[modules]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/modules.json
[native]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/native-validation.json
[probe]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/probe_context.py
[production]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/shared-handoff-validation.json
[production-probe]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/probe_shared_handoff.py
[audit]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/shared-loader-audit.json
[audit-source]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/audit_shared_loader.py
[version-asm]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/38-SoftwareVersion.asm
[system-asm]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/38-SystemConfig.asm
[bds-asm]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/38-Bds.asm
[os-gate]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/os-hardware-gate.asm
[os-startup]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/os-startup.asm
[seccore]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-context-20261117/seccore-entry.asm
[runtime-map]: ../../../ipod-firmware-lab/Classic38FW/evidence/runtime-map.json
[bridge]: ../../scripts/bootloader/loader/bds_bridge.S
[gate]: ../../scripts/bootloader/loader/gate.c
[version-source]: ../../scripts/bootloader/loader/software_version.c
