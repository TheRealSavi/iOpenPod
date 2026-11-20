# Shared Classic bootloader

The current Windows unlock installer ships one **2.1.0** executable for Classic
families 24, 33, 35 and 38. `classic-shared` contains one RAM writer, one pinned
manifest and ten source deltas for thirteen qualified migrations. Each delta reconstructs the identical body
SHA-256 `7d4e94a6a509713d92e3d54f839491e4152a2fb639fb178ad50d2aaf38abbe61`.
They encode migrations from four stock loaders, four earlier marked loaders and
the family-33 unmarked v5b loader, plus shared 2.0.0 on every Classic family.

The installer authenticates the live source, checks real SysCfg and the pinned
BootROM, then computes two 16-byte authentication values with that device's UKEY.
Only the initial IM3 header's two values are personalized. The shared executable
body and subsequent unsigned OS image remain identical across all four families.
The current shared body is recognized without rewriting it. Earlier unfinished
handoff receipts still permit only read-only verification.

The 2.1.0 release raises the schema-2 body limit for a 16 MiB OS slot. The
compiled gate differs from 2.0.0 only in two constant bytes; other modules and
file positions remain identical. Existing shared users need one DFU upgrade.
This expanded pair has not yet been physically installed. See
[expanded-space evidence](../../docs/research/classic-expanded-mod-space-2026-11-17.md).

## Shared build

The current source is the pinned family-38 Apple 2.0.5 loader and extracted
modules. ARM GNU 13.3.rel1, the pinned Go/wInd3x and Rockbox inputs described below
are maintainer tools. The installed application does not need them or the lab.

```powershell
uv run python -m scripts.bootloader.rebuild_loader `
  --shared --out .scratch/shared-loader --stock PATH/TO/38/apple-loader.bin `
  --modules PATH/TO/38/efi --toolchain PATH/TO/arm-toolchain/bin `
  --go PATH/TO/go.exe --wind3x PATH/TO/wInd3x

uv run python -m scripts.bootloader.build_bundle `
  --shared --stock PATH/TO/38/apple-loader.bin `
  --source 24=PATH/TO/24/apple-loader.bin `
  --source 33=PATH/TO/33/apple-loader.bin `
  --source 35=PATH/TO/35/apple-loader.bin `
  --loader .scratch/shared-loader/loader-body.bin `
  --previous-shared PATH/TO/2.0.0/loader-body.bin `
  --bootrom PATH/TO/bootrom.bin --toolchain PATH/TO/arm-toolchain/bin `
  --mkdfu-source PATH/TO/rockbox/utils/mks5lboot/mkdfu.c `
  --audit-directory .scratch/shared-writer --output-dir .scratch/shared-bundle
```

`--output-dir` also retains the common marked `loader-body.bin` for offline
comparison. Do not copy it into the distributable assets: ship deltas and the
sanitized writer. Without `--output-dir`, the builder writes those assets under
`src/iOpenPod/assets/bootloader/classic-shared`. It never accesses hardware.
The existing per-family assets are retained as qualified migration inputs and
for reproducible historical builds; the live installer selects the shared bundle.

The unmarked shared body is
`104c0d6453dc03e6cd8952c46855802dbbae91ffc8a1023a921ab0b474b17a32`.
The 64-byte identity record starts at body offset `0x1ad80`. Its schema and ABI
are 2, target is little-endian ASCII `CLSC` (`0x43534c43`), hardware mask is 15
(bits 0–3 mean revisions `0x130000`, `0x130100`, `0x130200`, `0x130300`), and
release text is `2.1.0`. The marker identifier remains `iOpenPod-Bootloader-v1`.
The marker is not a signing key or sufficient proof of installation.

## Native behavior and bounds

- Schema-2 OS images use `CLSC`, marker `IOPOD.UNSIGNED2`, the expanded body bound
  `0xfff800`, exact read counts and header/body CRCs.
- Schema-1 images retain their four family tags and respective original bounds
  for migration. Apple's signed path retains its authentication callbacks.
- SoftwareVersion accepts only the four known hardware revisions, the modern
  directory version range, and the older stock range only on family 24.
- After successful shared-OS validation, Bds invokes a ROM helper that changes
  only copied SysInfo words `0x84` and `0x11c` to `0x130300` and `0x01808003`.
  Native SystemConfig and flash SysCfg remain unchanged. Legacy handoffs retain
  their original values.
- DxeMain, PreEfi and the fixed SecCore tail stay at their original addresses.
  Bds's compressed growth is balanced by removing only debugger data from the
  immediately following relocatable ImageManagerSecurity module. All later
  pre-ROM file positions remain unchanged; executable security code is intact.
- The writer still touches only NOR `0x8000..0x28000`, commits the header sector
  last and verifies sector/full-flash digests. Per-device authentication and
  unknown-source rejection remain mandatory.

Independent extraction preserves 42 FFS files and 41 modules, with 37 modules
unchanged. Native validation passed 46,170 version-policy cases, 900 handoffs at
three relocation bases, 1,698 gate/bridge cases and 13 CRC cases. The actual
common OS passes the compiled header/body gates. Thirteen migrations produce the
same body; 27 incorrect source-family combinations are rejected. The packaged
writer passes eight simulated SST25 success/failure cases. Hardware callbacks,
SHA/full scans and peripherals are mocked where documented; this is not a
physical boot, USB-return or power-loss test. All four targets are enabled in
Device Summary by project-owner direction; see ADR-0282.

The preceding physical family-33 MB565 trial installed the 2.0.0 shared body
through the application installer. Its writer verified the complete NOR result
and unchanged bytes outside the boot span. It then booted the existing unsigned
2.0.1 OS and, after normal USB upload, the common 2.0.5 OS. The user confirmed
About, menus/clickwheel and headphone playback. Families 24, 35 and 38 remain
physically untested with the shared pair; power-loss recovery remains unqualified.
See the [physical trial](../../docs/research/classic-shared-205-os-layout-2026-11-17.md#physical-family-33-trial).

See [the boot audit](../../docs/research/classic-shared-205-boot-context-2026-11-17.md),
[the OS builder](../firmware/README.md), and
[ADR-0281](../../docs/adr/0281-share-classic-os-and-bootloader-artifacts.md).

## Historical family-specific bundles (1.0.0)

The following describes the previous outputs and their reproducible `--family`
builds. They are retained for migration and historical validation; these are not
the loader outputs selected by the current installer.

The application ships `stock.delta`, `writer.dfu`, `manifest.json` and `NOTICE.txt`
under `src/iOpenPod/assets/bootloader/classic{family}`. No compiler, sibling checkout,
complete Apple firmware, or device-specific signed loader is needed at runtime.

The Windows installer selects an exact updater family and Apple release, then
checks the live SysCfg identity, pinned S5L8702 BootROM and authenticated stock
loader. All writers require SST25VF080B NOR (`BF258E`). The physical baseline is
the family-33 MB565. The other three targets have offline and simulated
validation only; the wizard states this before installation.

| Family | Apple release | Retail models | Required SysCfg hardware | Marker offset | Fixed SecCore offset |
| --- | --- | --- | --- | --- | --- |
| 24 | 1.1.2 | MB029, MB147, MB145, MB150 | `0x00130000` | `0x1ad70` | `0x1f4f0` |
| 33 | 2.0.1 | MB562, MB565 | `0x00130100` | `0x1acc8` | `0x1f510` |
| 35 | 2.0.4 | MC293, MC297 | `0x00130200` | `0x1acf8` | `0x1f510` |
| 38 | 2.0.5 | MC293, MC297 | `0x00130300` | `0x1acf8` | `0x1f510` |

The per-family hardware pairing is a conservative eligibility policy. Some
cross-version installs accepted by upstream tools are deliberately outside it.
It is not proof that Apple forbids those combinations. Model names alone cannot
distinguish families 35 and 38. See the
[source comparison](../../docs/research/classic-bootloader-family-comparison-2026-11-17.md).

### Identity record

The 64-byte record begins at the per-target plaintext loader-body offset above,
within verified unused PAD FFS payload. Its FFS attributes do not enable a
payload checksum. On family 33, executable bytes, file starts and the fixed
SecCore entry remain unchanged from the physically tested v5b loader.

| Offset | Meaning |
| --- | --- |
| 0–31 | NUL-padded ASCII `iOpenPod-Bootloader-v1` |
| 32–35 | Little-endian record schema, 1 |
| 36–39 | Little-endian loader ABI, 1 |
| 40–43 | Little-endian updater family |
| 44–47 | Little-endian SysCfg hardware target |
| 48–63 | NUL-padded ASCII loader release, `1.0.0` |

The record is public identification, not a secret or a signing key. The installer
recognizes complete authenticated loader bodies by their pinned SHA-256 digest.
The earlier family-33 unmarked v5b digest is also recognized as unlocked and is not rewritten.
Normal-mode observation alone does not read this NOR record.

### Offline rebuild

Use Python through UV. Rebuilds additionally need ARM GNU 13.3.rel1, Go, Rockbox
`10ec9bd5`'s `utils/mks5lboot/mkdfu.c`, and wInd3x at
`7c7c4d83c8b923f29e7559585b2cdbbf4e028045`.
These are maintainer tools, not application dependencies. Inputs must be the
qualified stock plaintext loader, its extracted ROM and Bds PE32 modules, and
the qualified BootROM. All three loader inputs are hash checked. The extracted
modules retain their GUID filenames used by `rebuild_loader.py`. Select the same
`--family` in both steps; it defaults to 33 for the original workflow. Family
24, 35 and 38 require their own stock loader and modules, never family-33 inputs.

```powershell
uv run python -m scripts.bootloader.rebuild_loader `
  --family 38 --out .scratch/loader-rebuild --stock PATH/TO/apple-loader.bin `
  --modules PATH/TO/extracted-modules --toolchain PATH/TO/arm-toolchain/bin `
  --go PATH/TO/go --wind3x PATH/TO/wInd3x

uv run python -m scripts.bootloader.build_bundle `
  --family 38 --stock PATH/TO/apple-loader.bin --loader .scratch/loader-rebuild/loader-body.bin `
  --bootrom PATH/TO/bootrom.bin --toolchain PATH/TO/arm-toolchain/bin `
  --mkdfu-source PATH/TO/rockbox/utils/mks5lboot/mkdfu.c `
  --audit-directory .scratch/writer-rebuild
```

For family 33, the first stage reproduces the unmarked v5b digest
`fb0d5ebff7c97f3efb8de3e5b429e0b0bb698687b0aa7b1a8ef50d205c404f90`.
The bundle adds the record and produces body digest
`286656927ea39e2115583930d867ae810e715255b1b54ff6ca0a01e151caabea`.
The manifest and asset digests are pinned in the application. Deliberate changes
require reviewing those pins and repeating qualification. `profiles.py` holds
the exact build inputs and reviewed unmarked outputs; application targets pin
the marked output and manifest. `--output-dir` can place bundle rebuilds in a
separate local directory for comparison without replacing the shipped assets.

The sanitized writer has zero-filled slots for the authenticated header, packed
body, nonce and expected flash digests. The application fills them only after
matching the selected serial, model, hardware, BootROM and installed body. It
writes only NOR `0x8000..0x28000`, commits the header sector last, reads back each
sector and verifies full-flash/outside-region digests. A write is not atomic.
An interrupted installation can require a separate DFU recovery tool; this UI
provides result checking, not a general recovery installer.

### Provenance and validation

- `loader/`: the shared unsigned-OS gate, Bds bridge, CRC and repacker derived
  from the v5b research build. Exact original ROM/Bds/FirmwareFS code matches
  across the four releases. Family ID, body limit and packing remain per-target.
- `native/`: the physically exercised NOR writer with the packing gap adjusted
  by 64 bytes to preserve the new record; no new flash algorithm.
- SPI/SST25 code derives from Rockbox `10ec9bd5`, copyright 2009 Michael Sparmann.
- `native/vendor/`: SHA-256 and RAM return code from osos-lab
  `d2c8e357d58591bdaa70bb6be9da191f489554a6`, GPL-3.0-only.
- Python probe encodings derive from that osos-lab revision and its UKEY encryption
  extension, based on wInd3x, copyright 2022 Serge 'q3k' Bazanski,
  GPL-2.0-or-later, ported under GPL-3.0-only.
- The DFU certificate envelope follows Rockbox's `mks5lboot`.

On 2026-11-17, the portable loader rebuild reproduced v5b exactly. The marked
body was compared byte for byte outside its PAD record; all 169 applicable probe
vectors matched the independent lab package. The actual parameterized ARM writer
passed an in-memory SST25 model for success, wrong preimage, wrong JEDEC,
protection failure, failed write-enable, readback mismatch, erase timeout and
protection-restore failure. This model mocked SHA/full-flash scanning; it did not
simulate USB return, electrical behavior or power loss. Host tests independently
exercise seal framing, nonce/digest validation, one-time handoff, pending-result
recovery, cancellation and GUI ownership. The integrated wizard and new record
have not yet undergone a fresh physical installation.

The three added ports pass independent Reprise extraction: 42 FFS files remain,
only ROM and Bds executables change, and the other 39 modules are byte-identical
to their respective original loaders. All enabled checksums and fixed startup
positions pass. Each of the four compiled gates passes 1,674 native cases and
13 CRC cases; each actual packaged writer passes the eight SST25 model cases
above with synthetic flash contents. Family 33's loader and writer bytes remain
unchanged. These checks do not establish physical installation, USB return or
electrical behavior on the added targets. Receipts and repeatable native test
commands are linked from the family comparison.
