# Classic bootloader family comparison

Date: 2026-11-17. Scope: offline comparison of the original Apple loaders for
updater families 24, 33, 35 and 38. This investigation opened no USB interfaces,
executed no code on an iPod, and made no device writes. Its conclusions qualify
the source inputs and patch locations; they do not establish a physical install
or boot on the three additional families.

## Result

The Bds, ROM and IpodFirmwareFS modules are **byte-identical before their final
debug sections across all four releases**. The differences within those modules
are Apple build-path records in `.debug`. Therefore the existing family-33
instruction offsets, ROM protocol ABI, Bds stack slots and FirmwareFS length
semantics apply exactly to the other three supplied loaders. This is a complete
byte comparison of the relevant module prefixes, not a similarity score or
address-shift inference. [Comparison receipt][receipt], [comparison script][script].

The complete loaders are different. Their compressed FFS sizes, file positions,
padding and the family-24 SecCore position differ. The appropriate implementation
is a shared patch with pinned per-release inputs, updater-family fields, OSOS
limits and repacking layout. Applying the family-33 binary delta to another
loader is not valid. [Comparison receipt][receipt].

## Qualified original inputs

Every plaintext loader is 129,024 bytes (`0x1f800`) and contains 42 FFS files.
Each volume-header checksum, FFS header checksum and enabled FFS body checksum
passes. The PAD and SecCore files have body checksumming disabled; the report
marks that check inapplicable instead of interpreting their stored checksum byte
as a failure. [Comparison receipt][receipt].

| Family | Apple release | SHA-256 of stock plaintext loader |
| --- | --- | --- |
| 24 | 1.1.2 | `460368ec325ab567b3ea1d0c5e2eb09df7dac0502c1141257ffb32d661248f96` |
| 33 | 2.0.1 | `8d028296d20d7162eb109d062239ba510fe842510e006178040caacbabead1b8` |
| 35 | 2.0.4 | `7caf3863376cf7890adc73601d24fbf11bc9ce89c7b40366fd61b45a1d6633e8` |
| 38 | 2.0.5 | `d2670f7e5493c4b5ed4b9b6fa2029ce1e519c1927522384469e810fbf408fb5e` |

The sources are the retained [family-24 loader][loader24],
[family-33 loader][loader33], [family-35 loader][loader35] and
[family-38 loader][loader38]. The later loaders were independently extracted from
qualified AUPD captures; their provenance includes AUPD hashes, offsets and the
extractor fingerprint. [Family-35 extraction][extract35],
[family-38 extraction][extract38].

## Identical executable modules

The comparison asserts equality from module offset zero through the byte before
`.debug`. That includes PE headers, `.text`, `.data` and `.reloc`, with identical
section locations and entry points. The shared prefix hashes are:

| Module | Shared byte range | SHA-256 |
| --- | --- | --- |
| Bds | `0..0x1480` | `2e763e5c98672607a5c3c236ae644ba49276d0adb1458cc2c552029f59c4529a` |
| ROM | `0..0x1560` | `6587e11cbe555fc3e861d0e601a0bae3930caa0f61e22e2dc1ea0c55fb51c5c3` |
| IpodFirmwareFS | `0..0x12a0` | `3a16612fd2b156c35a5967876aeb99310a0d235dd2de7d4a6d8f18c21cfd1f1b` |

Full module fingerprints remain distinct and are recorded per family in the
[receipt][receipt]. A build should check those full hashes before replacing
`.debug`; prefix equality explains why one implementation is appropriate, but
does not permit arbitrary unrecognized inputs.

The existing hook sites match byte for byte in every family:

| Module offset | Original bytes/value | Purpose |
| --- | --- | --- |
| ROM `0x13d4` | LE pointer `0x7fb` | Header validator callback |
| ROM `0x6b2` | `02 22 98 47` | Inner body validator call |
| Bds `0x3d0` | `0f 98 08 99 83 68 01 22 98 47` | Header protocol call |
| Bds `0x3de` | `05 99 15 98 40 1a` | Original body allocation length |
| Bds `0x49c` | `09 9a 08 99 98 47` | Body protocol call |

The ROM continuation points remain failure `0x6d0`, success `0x6d4`, and native
header entry `0x7fa`. Code can occupy ROM's final debug section at `0x1560` and
Bds's 128-byte debug section at `0x1480` as in the existing patch.
[ROM disassembly][rom-asm], [existing bridge][bridge],
[existing linker map][linker], [comparison receipt][receipt].

The unchanged Bds native stack locations are header read count `SP+0x14`, body
read count `SP+0x18`, header buffer `SP+0x20`, body buffer `SP+0x24`, ROM protocol
`SP+0x3c`, media block size `SP+0x4c`, virtual file length `SP+0x54`, and development
fallback state `SP+0x60`. Bridge pushes must still be included when addressing
these slots. The shared IpodFirmwareFS code includes the original `Open` padding
rule, so the family-33 fix for declared versus inflated body size remains
necessary. [Existing bridge][bridge], [family-33 native length analysis][unsigned33],
[comparison receipt][receipt].

## Per-family layout and OSOS limits

Offsets below are relative to the plaintext loader body, not the IM3 header or
physical NOR. Repacking must preserve every early file's original location
through that family's ROM file start and preserve the original SecCore tail.
Only later driver files may shift into the existing PAD space, as in the current
family-33 strategy. [Original layout receipt][receipt], [existing repacker][repack].

| Family | Bds FFS start / unaligned size | ROM FFS start | Original PAD start / size | Fixed SecCore start / tail bytes |
| --- | --- | --- | --- | --- |
| 24 | `0x5d68 / 0xe6d` | `0x137a8` | `0x1a798 / 0x4d58` | `0x1f4f0 / 0x310` |
| 33 | `0x5d60 / 0xe67` | `0x13740` | `0x1a6e8 / 0x4e28` | `0x1f510 / 0x2f0` |
| 35 | `0x5d60 / 0xe68` | `0x13768` | `0x1a718 / 0x4df8` | `0x1f510 / 0x2f0` |
| 38 | `0x5d60 / 0xe67` | `0x13750` | `0x1a718 / 0x4df8` | `0x1f510 / 0x2f0` |

The family-24 SecCore is 32 bytes larger and begins 32 bytes earlier. Consequently
the writer's packed-tail reconstruction cannot retain the family-33 literal
`0x1f510 / 0x2f0` for that target. The identification record belongs in the rebuilt
target's verified unused PAD payload; its offset must come from the resulting
layout. [Original layout receipt][receipt].

The original IPSWs give these bounds for a custom OS image retaining the stock
partition layout:

| Family | OSOS start | Following AUPD start | Maximum body after a `0x800` header |
| --- | --- | --- | --- |
| 24 | `0x4e07000` | `0x5780000` | `0x978800` |
| 33 | `0x4e07000` | `0x580f000` | `0xa07800` |
| 35 | `0x4e07000` | `0x5824000` | `0xa1c800` |
| 38 | `0x5007000` | `0x5a2d000` | `0xa25800` |

The maximum is `next_entry_start - osos_start - 0x800`; the script parses every
original firmware directory and records the original IPSW and firmware-member
hashes. These limits are specific to the retained stock layouts. They are not a
claim about a repartitioned device or a general memory ceiling. The family field
in the custom header must also match the selected target. [Directory parser][directory],
[comparison script][script], [comparison receipt][receipt].

## BootROM, hardware identity and NOR

The pinned Reprise firmware manifest explicitly admits SysCfg hardware values
`0x00130000`, `0x00130100`, `0x00130200`, and `0x00130300`, all with BootROM SHA-256
`69c087afc5753d7f0f11f09b141b372af753a854bc526673ea444c486d6003e4`.
Its identity parser obtains this word at byte 4 within the `HwVr` record.
[Pinned manifest][manifest], [SysCfg implementation][syscfg].

Upstream fixtures associate the original Classic with `0x00130000`, the 120 GB
Classic with `0x00130100`, and later 160 GB revisions with `0x00130200` and
`0x00130300`. However, the same tests intentionally accept different Apple
releases on a hardware revision, including 2.0.5 on `0x00130200`. Firmware version
alone therefore does not establish hardware identity. A selected updater family
and exact authenticated loader digest should remain independent checks from the
live SysCfg hardware value. [Upstream identity tests][identity-tests].

The initial iOpenPod profiles conservatively pair 24 with `0x00130000`, 33 with
`0x00130100`, 35 with `0x00130200`, and 38 with `0x00130300`. This is an eligibility
policy for these exact targets, not a demonstrated Apple prohibition on other
combinations. Devices with an Apple release installed across revisions may be
refused even when upstream's broader policy would accept them. Matching the live
BootROM and authenticated stock-loader hashes remains necessary independently
of that pairing.

Rockbox's S5L8702 Classic implementation defines NOR size `0x100000`, original
boot offset `0x8000`, and maximum boot span `0x20000`. Its flash driver uses the
same SPI read, sector erase and AAI word-program sequence from which the current
writer derives. These are upstream implementation facts, not new measurements
on families 24, 35 or 38. [NOR layout][nor-layout], [NOR driver][nor-driver].

No new-family physical NOR manufacturer capture was established in this review.
The current writer's `BF258E` JEDEC requirement must remain enforced; a different
chip must be rejected before erase rather than inferred compatible from its
Classic label. The full BootROM hash check must also remain mandatory before
using the fixed native helper addresses. [Current writer][writer],
[current DFU qualification][dfu].

## Independent candidate audit

The four unmarked outputs from `.scratch/classic-family-port-20261117` were
independently extracted with the pinned Reprise EFI extractor, separate from the
wInd3x library used to repack them. An independent audit of the resulting bytes
passes for every target: [audit implementation][audit-script],
[audit receipt][audit].

- Exactly 42 FFS files remain in the same order; the volume-header checksum,
  every FFS header checksum, and every enabled body checksum pass.
- Exactly 41 executable modules are extracted. Bds and ROM change; the other
  39 modules are byte-identical to their own original target.
- Only Bds, ROM and PAD FFS byte contents change. Every early file position
  through the ROM file is preserved, and the original SecCore tail is exact.
- Within native executable and data sections, changes are confined to the
  two ROM patch locations and three Bds hook locations listed above.
- New ROM gate bytes differ from family 33 only at the family comparison
  instruction (`RVA 0x15d0`) and maximum-body-minus-16 literal (`RVA 0x166c`).
  The compiled limits equal the independently parsed original directory limits.
- The rebuilt family-33 body reproduces the physically tested unmarked v5b
  hash exactly. The other three are new offline candidates.

| Family | Unmarked candidate SHA-256 | Rebuilt PAD payload start |
| --- | --- | --- |
| 24 | `42d18c4828a7fe84380d85dfd759948f511af8a9fd35bea0a53b2656787a169c` | `0x1ad70` |
| 33 | `fb0d5ebff7c97f3efb8de3e5b429e0b0bb698687b0aa7b1a8ef50d205c404f90` | `0x1acc8` |
| 35 | `aa5307e1e39bb5f26e7506acd16d493b29ba5f2e18fe8279175686f3a1c4969d` | `0x1acf8` |
| 38 | `1bfcee49f13331378d3d4478ed970893d4cd1d0badbb5e82138ee4f4e0927b2d` | `0x1acf8` |

These hashes precede adding the identification record. The audit separately
asserts that each rebuilt PAD payload is entirely `0xff`, providing the bounded
region into which that record can be inserted. [Audit receipt][audit].

## Native execution and distributable bundles

The subsequent offline run executes each compiled ROM gate and the actual patched
Bds call sites at three relocated addresses. All four targets pass 1,674 cases
covering Apple-format dispatch, target and framing checks, malformed lengths,
short reads, FirmwareFS allocation and rejection paths. Thirteen CRC cases per
target include an OS-sized buffer. Native Apple validator callbacks are mocked;
this is not an authenticated hardware boot. [Native receipt][native-receipt],
[gate test source][native-source].

Each actual shipped writer template, filled through `BootloaderBundle.writer`,
also passes eight native SST25 model cases: success, wrong preimage, wrong JEDEC,
protection failure, failed write-enable, readback mismatch, erase timeout and
protection-restore failure. Synthetic flash contents contain no device identity.
These cases verify target reconstruction, including family 24's different SecCore
tail, bounded writes and header-sector-last order. SHA/full-flash scanning and
peripherals are mocked as recorded. [Native receipt][native-receipt],
[writer model source][writer-source].

The resulting bundles are selected by exact family and release. Their marked
body hashes are:

| Family | SHA-256 of marked loader body |
| --- | --- |
| 24 | `2f29ceef5ad494885cc81e390261b34227bdc6d14ec455224c7e4272e052f5cf` |
| 33 | `286656927ea39e2115583930d867ae810e715255b1b54ff6ca0a01e151caabea` |
| 35 | `641f4adbcad34a36845f4dfffe3cf97fc8f4373f4f85693c6980a4f3501ac002` |
| 38 | `4db5f3d96d5a7544f9a70fd2c271fbaf26d4f675995423a167a0d1d23d402f19` |

Family 33's marked loader and writer remain byte-identical to the prior bundle.
Its manifest now includes the same explicit layout fields as the other targets.
[Native receipt][native-receipt], [build instructions][build-instructions].

After rebuilding a family, run the native gate regression with the lab script:

```powershell
uv run --with unicorn==2.1.4 python ../ipod-firmware-lab/scripts/test_classic_bootloader_families.py --build PATH/TO/loader-build
```

The writer model accepts `--build PATH/TO/writer-audit` containing `symbols.txt`,
the parameterized `helper.bin` (DFU image after its `0x30c` envelope), and synthetic
`before.bin`/`candidate.bin`. Its inputs must be filled using the actual selected
bundle, as in this audit; the default unfilled writer template is not executable
test input. No script opens USB or a physical disk.

## Validation boundary

This comparison establishes exact source equality and differing container
parameters, and verifies the resulting candidate structure. The separate native
tests above execute the new patches in software. Neither establishes flash
timing, hardware return paths, physical startup of the added targets or recovery
after power loss. Physical installation results remain distinct from these
static and emulated findings.

Reproduction uses `uv run` on the [saved script][script], with Capstone 5.0.6
pinned by its inline metadata. The analysis artifacts are ignored local firmware
research inputs and outputs. Upstream source revisions used here are osos-lab
`d2c8e357d58591bdaa70bb6be9da191f489554a6`, wInd3x
`7c7c4d83c8b923f29e7559585b2cdbbf4e028045`, and Rockbox
`10ec9bd530c852631ce126795cacf20e7578017f`.

[receipt]: ../../../ipod-firmware-lab/artifacts/classic-bootloader-family-comparison-20261117/comparison.json
[script]: ../../../ipod-firmware-lab/artifacts/classic-bootloader-family-comparison-20261117/compare.py
[loader24]: ../../../ipod-firmware-lab/artifacts/classic24-early-boot-20261105-v1/apple-loader.bin
[loader33]: ../../../ipod-firmware-lab/Classic33FW/firmware/analysis-inputs/apple-loader.bin
[loader35]: ../../../ipod-firmware-lab/artifacts/later-classic-efi-20261105-v1/35/apple-loader.bin
[loader38]: ../../../ipod-firmware-lab/artifacts/later-classic-efi-20261105-v1/38/apple-loader.bin
[extract35]: ../../../ipod-firmware-lab/artifacts/later-classic-efi-20261105-v1/35/receipt.json
[extract38]: ../../../ipod-firmware-lab/artifacts/later-classic-efi-20261105-v1/38/receipt.json
[rom-asm]: ../../../ipod-firmware-lab/artifacts/classic-bootloader-family-comparison-20261117/33-ROM.asm
[bridge]: ../../scripts/bootloader/loader/bds_bridge.S
[linker]: ../../scripts/bootloader/loader/gate.lds
[unsigned33]: classic33-unsigned-boot-path-2026-11-17.md
[repack]: ../../scripts/bootloader/loader/repack.go
[directory]: ../../../ipod-firmware-lab/scripts/extract_classic_ipsw.py
[manifest]: ../../../ipod-firmware-lab/vendor/osos-lab/firmware/apple.json
[syscfg]: ../../../ipod-firmware-lab/vendor/osos-lab/host/crates/reprise-device/src/syscfg.rs
[identity-tests]: ../../../ipod-firmware-lab/vendor/osos-lab/host/crates/reprise-device/src/tests.rs
[nor-layout]: ../../../ipod-firmware-lab/vendor/rockbox-classic-acquisition/firmware/target/arm/s5l8702/norboot-target.h
[nor-driver]: ../../../ipod-firmware-lab/vendor/rockbox-classic-acquisition/firmware/target/arm/s5l8702/norboot-s5l8702.c
[writer]: ../../scripts/bootloader/native/helper.c
[dfu]: ../../src/iOpenPod/app/firmware/bootloader_dfu.py
[audit-script]: ../../../ipod-firmware-lab/artifacts/classic-bootloader-family-comparison-20261117/audit_candidates.py
[audit]: ../../../ipod-firmware-lab/artifacts/classic-bootloader-family-comparison-20261117/candidate-audit.json
[native-receipt]: ../../../ipod-firmware-lab/artifacts/classic-bootloader-family-comparison-20261117/native-validation.json
[native-source]: ../../../ipod-firmware-lab/scripts/test_classic_bootloader_families.py
[writer-source]: ../../../ipod-firmware-lab/scripts/test_classic_bootloader_writers.py
[build-instructions]: ../../scripts/bootloader/README.md
