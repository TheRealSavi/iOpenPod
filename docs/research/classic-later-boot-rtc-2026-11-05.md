# Later Classic boot and RTC evidence boundary

Research begun **2026-11-05**, completed **2026-11-06, America/Detroit**. Targets are independently
qualified updater family **35 / RetailOS 2.0.4** and **38 / RetailOS 2.0.5**.
Their latest-release identities are established by the separate
[Apple catalog investigation](classic-latest-firmware-targets-2026-11-05.md).

Both missing plaintext AUPDs were acquired using the user-supplied Classic 6.5,
as recorded in the separate [hardware acquisition report][acquisition]. Their
extracted loaders match the independently pinned family-specific hashes. This
report now traces actual EFI, updater and Disk Mode bytes, closing the former
input boundary. The traces and bounded native probes are offline; the physical
iPod performed decryption, not execution of these later target firmwares.

Both loaders perform an early PMU write of `0x58=0`, whose exact hardware effect
remains unknown. No identified initialization write spans the RTC registers
`0x59..0x6e`. Disk Mode calendar setting uses software correction; the identified
raw-write route selects the alarm bank. These findings still do **not** establish
a running RTC seed, power-loss default or UTC/local origin. [EFI receipt][efi-receipt],
[Disk Mode receipt][disk-receipt]

This limitation is separate from the already byte-verified later OSOS contracts
in the [raw-clock report](classic-raw-clock-origin-followup-2026-11-05.md) and
[calendar report](later-classic-latest-calendar-contracts-2026-11-05.md). Unknown
raw-clock origin continues to be optional metadata uncertainty under
[ADR-0240](../adr/0240-treat-calendar-dates-as-best-effort-metadata.md).

## Exact archive and component inventory

The new [guarded script][script] validates complete IPSW hashes, ZIP integrity,
the two-member ZIP inventory, Apple manifest family/build values, firmware-member
hashes, directory bounds, and AUPD framing before writing a new output directory.
The retained [receipt][receipt] records the original component offsets and
hashes, all output hashes, tool/source hashes, and upstream map metadata.

| Target | IPSW SHA-256 | Firmware member SHA-256 |
| --- | --- | --- |
| 35 / 2.0.4 | `7ef835c74b08f0bda3566001496cb764afbe0600cb1afec1145c259bc34ad7d0` | `0b36bdb4b93685a4cb24153201a96f44124d9f50eb7c6239e203d3e917405942` |
| 38 / 2.0.5 | `80f974edea54ae4c9b659578a0c4d74438ffd94b8270944ec0cfc8f10e90eb2d` | `9450c5b51f8785d41c1eef041eac3c7a521d0b325d730f591759b49d041086aa` |

Each archive contains exactly `manifest.plist` and its `Firmware-35.9.0.4` or
`Firmware-38.9.0.5` member. Each firmware directory contains four entries:
`rsrc`, `osos`, `aupd`, and `hash`. There is no separate plaintext loader or EFI
ZIP member. This is an exact archive-inventory statement, not proof that no
executable exists within one of the components. [Receipt][receipt].

| Target | Non-OSOS entry | Firmware offset | Preserved component extent |
| --- | --- | ---: | ---: |
| 35 | `rsrc` | 24,576 | 81,793,024 bytes |
| 35 | `aupd` | 92,422,144 | 1,169,587 bytes |
| 35 | `hash` | 93,593,600 | 8,192 bytes |
| 38 | `rsrc` | 24,576 | 83,890,176 bytes |
| 38 | `aupd` | 94,556,160 | 1,169,587 bytes |
| 38 | `hash` | 95,727,616 | 8,192 bytes |

These extents follow the already validated directory rule of recorded length
plus `0x1000` container overhead. They are not executable-memory mappings.
The receipt inventories all four entries per target, including complete hashes.
The two `hash` components are byte-equivalent by their common SHA-256; this
does not establish loader reuse. [Directory parser][directory], [receipt][receipt].

## Qualified encrypted inputs and acquired plaintext

| Property | 35 / 2.0.4 | 38 / 2.0.5 |
| --- | --- | --- |
| IMG1 family/version/format | `8702` / `1.0` / encrypted format 3 | Same |
| IMG1 header extent | `0x800` | `0x800` |
| Logical body extent | 1,164,356 bytes | 1,164,360 bytes |
| AES-rounded body extent | 1,164,368 bytes | 1,164,368 bytes |
| Final block padding beyond logical extent | 12 bytes | 8 bytes |
| Extracted encrypted IMG1 extent | 1,166,416 bytes | 1,166,416 bytes |
| Encrypted IMG1 SHA-256 | `c3252a3a4921e49e44f4d37aa56be7af07e53489ce11d9a66e44da634716f3d5` | `c49b4796d9370b80713b3eaaa0c8053388a6efd568a1f2cce9631c276c817d27` |
| Ciphertext SHA-256 | `515deec682ca1894e271de8cbf21058c4700b273161cefbb56a83b67f5483b61` | `566800cf6d8eeab62365b37c0f4e817f76ad5ff794cf82d27237837ca96a1474` |

The input artifact contains a byte-preserving IMG1 extraction and its ciphertext
body for each target, with explicitly encrypted filenames. It also preserves
each manifest. No ciphertext was disassembled as instructions, and no plaintext
was synthesized. [Receipt and output inventory][receipt].

The pinned [`decrypt` implementation][decrypt] invokes a checked device's AES
engine with key selector one and carries the preceding ciphertext block as the
next chunk's IV. The [`decrypt-nor` CLI route][firmware-cli] also requires device
operations; its name does not describe a purely offline decryptor. The separate
[`extract-efi` implementation][efi] operates offline on an already plaintext
loader, requiring a valid EFI volume at loader offset `0x100`. The authorized
acquisition used the generic device decryption route; the subsequent
[loader extractor][extractor] verified each captured body and found the embedded
loader by its exact expected hash before invoking offline EFI extraction.
Encrypted bytes were never treated as instructions.

| Target | Captured padded AUPD SHA-256 | Loader offset in body |
| --- | --- | --- |
| 35 | `34d5fa37dbc3ad9e3fa818021263064244a37274b95a5680072b8a7f33c17f2d` | `0x24428` |
| 38 | `9fdd2f354eb345ef0ff65dbc5ac7479720232e52d02e36b53cf1c711aa1a6095` | `0x2442c` |

Both padded bodies have 1,164,368 bytes. The 38 body matches an independently
pinned whole-body hash; the 35 body hash is newly measured, with independent
qualification supplied by its embedded loader hash. [Acquisition][acquisition],
[35 extraction][extract35], [38 extraction][extract38]

A preliminary bounded reuse check compared every aligned 16-byte later AUPD ciphertext block
against the preserved 33/2.0.1 AUPD ciphertext. Both later targets match only
the initial 224 bytes, fourteen blocks at the same offsets; there are no further
matches in this comparison. The known 33 plaintext and ciphertext are separately
hash-guarded. This does not recover either later embedded loader, reveal a key,
or prove the absence of other offline recovery methods. It supplies no running
RTC contract. [Comparison assertions and control identities][receipt].

## Loader identity and upstream annotations

Pinned osos-lab revision
`d2c8e357d58591bdaa70bb6be9da191f489554a6` records distinct expected loader
fingerprints:

| Target | Expected plaintext loader bytes | Expected SHA-256 |
| --- | ---: | --- |
| 33 / 2.0.1 control | 129,024 | `8d028296d20d7162eb109d062239ba510fe842510e006178040caacbabead1b8` |
| 35 / 2.0.4 | 129,024 | `7caf3863376cf7890adc73601d24fbf11bc9ce89c7b40366fd61b45a1d6633e8` |
| 38 / 2.0.5 | 129,024 | `d2670f7e5493c4b5ed4b9b6fa2029ce1e519c1927522384469e810fbf408fb5e` |

Both later acquired plaintext loaders now match these expected fingerprints.
Each yields **41 EFI modules**, with individual hashes retained in its extraction
receipt. Equal length alone was never used to establish instruction equivalence.
[35 profile][profile35], [38 profile][profile38], [35 extraction][extract35],
[38 extraction][extract38]

Each later NOR export contains annotations for 39 module directories plus a
boot image. That is the export's coverage count, not a verified count of modules
in the complete later loader. Its forty memory-map companions per target are
all referenced as absent `*.elf.sarif.bytes` files. The `DxePcf50635` code exports
contain address/length spans, not opcodes or instruction bytes; function exports
add signatures and stack descriptions rather than executable bodies. This data
is insufficient to independently trace PMU register arguments or RTC writes.
[35 map][pmu-map35], [38 map][pmu-map38], [export audit][receipt].

The PMU maps themselves differ. These coordinates are **upstream
module-relative annotations**, not verified live addresses:

| Exported region | 35 annotation | 38 annotation |
| --- | --- | --- |
| `.text` | RVA `0x220`, 3,300 bytes | RVA `0x220`, 3,304 bytes |
| `.data` | RVA `0xf04`, 220 bytes | RVA `0xf08`, 248 bytes |
| `.reloc` | RVA `0xfe0`, 64 bytes | RVA `0x1000`, 64 bytes |

The receipt preserves the complete maps and hashes of each PMU export file.
These differences are reasons to keep the targets separate, not evidence of a
particular RTC behavior change. The known 33 generic PMU helper and protocol
findings were not promoted to either later target; actual later-byte checks
below supply the independent evidence.
[35 map][pmu-map35], [38 map][pmu-map38].

## Actual EFI initialization and PMU consumers

These coordinates are PE module-relative RVAs. A preferred ImageBase is not a
measurement of the module's eventual live address. [EFI receipt][efi-receipt]

| Role | 35 | 38 |
| --- | --- | --- |
| PreEfi preferred ImageBase | `0x2200e1fc` | `0x2200e1f4` |
| PreEfi Thumb entry | `0x2351` | `0x2351` |
| Entry call to PMU initializer | `0x236e` to `0x070e` | Same |
| DxePcf50635 Thumb entry | `0x5ef` | `0x5f5` |
| Generic PMU interface | `0xf2c` | `0xf30` |
| Thumb read/write methods | `0x221` / `0x24d` | Same |

The complete audited helper/initializer span `0x05ce..0x095e` includes the
initializer's return instruction at `0x095c`. That span and entry span
`0x2350..0x23cc` match the qualified 33 bytes, with each later module independently
hashed and checked. For each target, 29 native Thumb cases exercise the four
relevant status-bit combinations and each of 25 PMU-operation error prefixes.
Successful initialization produces 21 writes, including `0x58=0`; no written
span touches `0x59..0x6e`. This does not assign register `0x58` a meaning or prove
that the RTC survives initialization unchanged. [Native traces and guards][efi-receipt]

Actual DxePcf protocol registration installs the generic interface under GUID
`3d4aa229-b4e3-4fd9-9ec9-90ea8123833e`. Its exact GUID occurs only in DxePcf and
Ata among each loader's 41 modules. The SMBus GUID occurs in DxePcf and DxeSmbus.
Native execution of Ata's write block `0x350..0x366` verifies the two-byte write
`0x1a <- 6b01`. The PMU methods use endpoint `0x73`. Exact GUID occurrences bound
this identified consumer set; they do not exclude computed access or untraced
callers elsewhere. [EFI receipt][efi-receipt]

The final EFI receipt records **62 native cases, 34 byte guards and 14 disassembly
spans**, with explicit PMU/EFI service mocks. It is neither a complete boot nor a
hardware acceptance test. [Verifier][efi-script], [receipt][efi-receipt]

## Updater executable PMU surface

The [all-four updater audit][updater-receipt] independently pins input hashes,
startup extents and actual call sites. Families 35/38 both have PMU reader
`0x0800f7b4` (84 bytes) and writer `0x0800f848` (60 bytes); these two routines
match exactly across the later pair. Their surrounding 848-byte PMU block differs
at three global-address literals, and startup code extents differ by four bytes.
This is selected-range parity, not whole-updater equivalence.

Both later images have the same seven direct PMU write sites and register/length
arguments as qualified family 24: `1a/1`, `29/1`, `52/1`, `53/2`, `28/1`, `1d/1`
and `1b/1`. The `28/1` route is conditional. None of these spans reaches
`0x59..0x6e`. Lower I2C writer `0x0800d708` has direct callers `0x0800f7d4` and
`0x0800f87c`; reader `0x0800d510` has caller `0x0800f7ec`. Exact aligned pointer
scans find no aliases to the four selected PMU/I2C routines. Computed pointers
and other peripheral access remain outside this static claim. The receipt
contains **88 word guards, 40 call guards and 24 listings across all four
targets**. [Updater verifier][updater-script], [receipt][updater-receipt]

## Independent Disk Mode clock paths

Each disk image is identified through its actual AUPD footer and verified against
its stored additive checksum and exact SHA-256. [Disk receipt][disk-receipt]

| Target | AUPD offset / bytes | Disk image SHA-256 |
| --- | --- | --- |
| 35 | `0xe7728` / `0x34af4` | `897b760d6c3c8e56934ec19d947a1942d722cbc65c3e075dc459af2fb6728264` |
| 38 | `0xe773c` / `0x34af0` | `2bddafcae7bfb7c7e7e781971bb1fa64605b220bd37fefdd0361c1120960561f` |

Native execution of each startup copy establishes the `0x730`-byte image prefix
at IRAM `0x22000000` and the remaining initialized region at DRAM `0x08000000`.
The DRAM extents are `0x343c0` for 35 and `0x343bc` for 38; their BSS extents are
`0x1089c` and `0x108a0`, both ending at `0x08044c5c`. Four tail bytes are not
copied. Therefore a DRAM function's runtime address is the base plus its file
offset minus `0x730`, not the base plus file offset. [Map guards][disk-receipt]

Six bounded native cases per target execute startup relocation, plus/minus one
hour of calendar correction, alarm-selector dispatch to a stubbed raw writer,
and valid/invalid retained metadata restoration. The calendar setter reads raw bank **zero** and updates
software correction. The identified raw-write caller selects bank **one**, the
alarm; the downstream bank mapping is separately byte-guarded static evidence.
Direct ARM call scans find only this alarm chain into the raw wrapper and
bank writer, and no exact aligned function pointers in the checked initialized
regions. This does not exclude computed calls or other images. [Disk verifier][disk-script],
[guards and native cases][disk-receipt]

Invalid retained metadata initializes shared RAM to **2000-01-04 midnight**,
with zero offset/DST. The bounded fallback performs no raw-clock or PMU access.
That software default is not proof of the running RTC's initial calendar.
The final disk receipt records **12 native cases, 70 byte/call guards and 38
disassembly spans** across the two targets. [Disk receipt][disk-receipt]

## Remaining questions and application effect

For **35/2.0.4** and independently for **38/2.0.5**, the missing-loader boundary
is closed. Remaining seams include exact PMU register `0x58` semantics,
BootROM/factory and diagnostic-image clock initialization, complete boot/handoff
scheduling, computed peripheral access, and physical power-loss behavior. Neither
an exposed generic PMU writer nor the software fallback proves a UTC/local origin.

Unknown raw-clock origin remains optional metadata uncertainty under ADR-0240.
The application preserves native date words and uses best-effort interpretation;
these results introduce no device clock writer or Library prerequisite. The
[early-target report](classic-early-boot-rtc-2026-11-05.md) supplies the independently
qualified 24/33 comparison.

Reproduce the checks from the firmware lab using fresh output directories:

```powershell
uv run scripts/check_later_classic_boot_inputs.py --output-dir artifacts/later-input-repeat
uv run scripts/check_later_classic_efi_rtc.py --output-dir artifacts/later-efi-repeat
uv run scripts/check_later_classic_disk_clock.py --output-dir artifacts/later-disk-repeat
uv run scripts/check_all_classic_aupd_pmu_parity.py --output-dir artifacts/updater-pmu-repeat
```

Receipts record Python 3.12.14, Capstone 5.0.6 and Unicorn 2.1.4 where used, script
hashes, inputs, guards and native case results. Research script Ruff checks passed.
Firmware originals and shared Ghidra projects remain unchanged. Physical
decryption provenance and subsequent stock-menu confirmation are documented
separately in the acquisition report.

[script]: ../../../ipod-firmware-lab/scripts/check_later_classic_boot_inputs.py
[acquisition]: classic-aupd-hardware-acquisition-2026-11-05.md
[extractor]: ../../../ipod-firmware-lab/scripts/extract_later_classic_aupd_loaders.py
[extract35]: ../../../ipod-firmware-lab/artifacts/later-classic-efi-20261105-v1/35/receipt.json
[extract38]: ../../../ipod-firmware-lab/artifacts/later-classic-efi-20261105-v1/38/receipt.json
[efi-script]: ../../../ipod-firmware-lab/scripts/check_later_classic_efi_rtc.py
[efi-receipt]: ../../../ipod-firmware-lab/artifacts/later-classic-efi-rtc-20261106-v2/receipt.json
[disk-script]: ../../../ipod-firmware-lab/scripts/check_later_classic_disk_clock.py
[disk-receipt]: ../../../ipod-firmware-lab/artifacts/later-classic-disk-clock-20261106-v2/receipt.json
[updater-script]: ../../../ipod-firmware-lab/scripts/check_all_classic_aupd_pmu_parity.py
[updater-receipt]: ../../../ipod-firmware-lab/artifacts/all-classic-aupd-pmu-parity-20261105-v1/receipt.json
[receipt]: ../../../ipod-firmware-lab/artifacts/later-classic-boot-inputs-20261105-v2/receipt.json
[directory]: ../../../ipod-firmware-lab/scripts/extract_classic_ipsw.py
[decrypt]: ../../../ipod-firmware-lab/vendor/osos-lab/host/crates/reprise-device/src/decrypt.rs
[firmware-cli]: ../../../ipod-firmware-lab/vendor/osos-lab/host/crates/reprise-cli/src/firmware.rs
[efi]: ../../../ipod-firmware-lab/vendor/osos-lab/host/crates/reprise-bundle/src/preparation/efi.rs
[profile35]: ../../../ipod-firmware-lab/vendor/osos-lab/ghidra/profiles/classic7g-2.0.4.json
[profile38]: ../../../ipod-firmware-lab/vendor/osos-lab/ghidra/profiles/firmware-2.0.5.json
[pmu-map35]: ../../../ipod-firmware-lab/vendor/osos-lab/ghidra/analysis/2.0.4/NOR/modules/DxePcf50635-4c8b3791-8858-4de9-8cac-7aee7d214678/memory_map.jsonl
[pmu-map38]: ../../../ipod-firmware-lab/vendor/osos-lab/ghidra/analysis/2.0.5/NOR/modules/DxePcf50635-4c8b3791-8858-4de9-8cac-7aee7d214678/memory_map.jsonl
