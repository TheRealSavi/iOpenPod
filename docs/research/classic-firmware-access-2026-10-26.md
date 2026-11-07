# Direct Classic firmware access

Research date: **2026-10-26**. Target selected by the user: **iPod Classic
6th/7th generation**, including the 120 GB revision commonly called 6.5G.
This is source research and a local evidence inventory. No firmware tool was
built or executed, firmware acquired, or physical iPod accessed for this review.
Prior local experiments are identified separately.

## Assessment

The strongest combination among the seven supplied projects is **osos-lab for
Classic firmware analysis and patch construction**, with **qemu-ipod-classic as
an experimental execution instrument**. Neither a successful Ghidra import nor
an emulator menu establishes acceptance or correct playback on a physical iPod.
This recommendation follows the source findings below; it is not an adopted
iOpenPod architecture or an implementation claim.

The immediate prerequisite is a versioned, hash-identified Classic firmware
corpus. Existing iOpenPod research records a physical 120 GB Classic running
RetailOS **2.0.1**, whereas current osos-lab builds target **2.0.5**. These are
different research subjects. A later patched release cannot by itself explain
the behavior of the existing stock device. [Local Genius investigation][local-genius],
[upstream firmware manifest][osos-manifest].

## Project comparison

| Project | Actual role and scope | Use for this Classic investigation |
| --- | --- | --- |
| [osos-lab / RepriseOS][osos-readme] | Classic firmware analysis, patch recipes, native payloads, loader and device tools. | Primary candidate. Includes versioned Ghidra annotations and concrete hooks into Apple code. |
| [qemu-ipod-classic][qemu-readme] | Executes Classic 6G S5L8702 RetailOS and also has a separate Video target; supplies boot handoff rather than executing Apple's BootROM. | Relevant dynamic-analysis candidate, with substantial fidelity limits and no established 2.0.5 pairing. |
| [clicky][clicky-status] | PortalPlayer emulator focused on grayscale 4G; later Samsung Classic devices are outside its scope. | Useful debugger/hardware-model reference, not a Classic execution backend. |
| [siggifly/ipod-emulator][siggi-readme] | Video 5G/5.5G firmware execution, image tools, tracing, and GUI. | Existing local Video results are useful methodology; its machine model does not supply Classic emulation. |
| [iPodWizard-mirror][wizard-readme] | Historical v1.3 Windows firmware/resource editor, including persistent raw disk writes. | Resource/container reference. No dependable Classic 6G/7G support matrix was established. |
| [wInd3x][wind-readme] | BootROM/DFU exploitation, memory reads, IMG1 decryption and temporary custom firmware loading, principally nano. | Important implementation lineage. README Classic claims and current CLI registration disagree. |
| [Xlinka/iPodReverseEngineering][xlinka-tree] | Small collection of historical reference assets, including an iPod games paper, hardware datasheets and an image. | Background material, not an extraction, patching, or emulation toolchain. |

All emulator descriptions above concern execution of guest software. Their
substituted hardware and boot paths still constrain which firmware behavior can
be inferred from a run. [QEMU machine][qemu-machine], [Video assessment][local-video].

## osos-lab provides the most direct route

### Reading Apple code

The repository retains separate analysis profiles for 2.0.1, 2.0.4, and 2.0.5.
Profiles specify input lengths and SHA-256 hashes, runtime memory regions, source
offsets, and entry points. This matters because the OS is relocated: loading every
byte at one arbitrary base address would misrepresent startup and runtime code.
The 2.0.5 profile separates DRAM, IRAM and zero-initialized regions.
[2.0.5 profile][osos-profile], [2.0.1 profile][osos-old-profile].

Reading firmware here means disassembly, reconstructed decompiler pseudocode,
data structures, strings, references, and analyst annotations. It does not recover
Apple's original source project or prove every inferred function name. The saved
analysis is a starting point to verify against the exact binary and its observed
behavior. [Saved analysis][osos-analysis], [reference qualifications][osos-docs].

The existing prose reference explicitly describes **2.0.4 Classic 7G Rev B**
addresses while active builds use **2.0.5**. It warns against transferring those
addresses between versions. Its OSOS notes cover relocation, task creation,
graphics, storage initialization, fonts, and the native audio pipeline.
[Reference scope][osos-docs], [OSOS runtime notes][osos-runtime].

### Extracting is different from decrypting

The Host tools distinguish offline IPSW inspection/extraction from device-assisted
decryption. `firmware extract` returns encrypted OSOS. The `decrypt` operation
opens a checked device session and returns the plaintext IMG1 body, including AES
padding. `firmware prepare` can accept that body and reconstruct the expected
image before validating prepared inputs. A filename such as `osos.bin` alone is
therefore insufficient provenance: record whether it includes the IMG1 header,
which padding remains, and which transformations produced it.
[Firmware commands][osos-firmware-cli], [decryption implementation][osos-decrypt].

The CLI distinguishes device enumeration, a DFU state query, BootROM/identity
checks, and a full 1 MiB NOR read with cross-checks. The checks and decryption use
BootROM DFU and payload execution; they are not ordinary filesystem reads or
passive inspection of the currently running RetailOS. No such operation was
performed in this investigation. [CLI behavior][osos-cli], [USB session][osos-usb].

The USB source contains a Windows Apple DFU backend as well as libusb. This is
concrete Windows implementation evidence, not proof of a successful build or
compatible driver setup on this Host. The shared Classic/nano 3G DFU USB ID is
only a candidate identifier; the later BootROM fingerprint and hardware checks
establish the tool's supported target. [USB source][osos-usb],
[checks][osos-checks], [compatibility manifest][osos-manifest].

### Modifying Apple code

Patch declarations identify addresses, expected original instructions or pointers,
and replacement code. Assembly recipes validate input fingerprints and patch
preimages. This supplies a useful model for reproducible changes: preserve the
original, reject a mismatched binary, and create a separate result.
[Patch declarations][osos-patch-types], [recipe checks][osos-recipes].

The Album Artist implementation is a particularly relevant study subject for
iOpenPod: the patch table hooks the iTunes importer and the native path that
discards the Album Artist MHOD, then changes browser/menu behavior. This provides
a concrete path from a database field to firmware behavior that can be traced and
tested. It does not establish an unchanged firmware capability on every Classic.
[Native patch sites][osos-patches].

RepriseOS uses a modified Rockbox bootloader in NOR, disk-resident OSOS/payload
files, and an Apple companion loader executing in RAM. The companion initializes
Apple drivers and hands off to the OS. Consequently, RAM-resident Apple patches
do **not** mean that installing this boot arrangement leaves persistent storage
unchanged. Device identity is used when assembling the companion.
[Boot sequence][osos-boot], [bundle and Host tools][osos-host].

For the reviewed source, Ghidra tooling specifies 12.1.4 with JDK 21+, and firmware
payload builds specify Rockbox's ARM GCC 9.5.0 toolchain plus Python, Make, Perl
and a Host compiler. Host tools use Rust/libusb. These are upstream requirements,
not installed or newly validated dependencies for iOpenPod. [Build/import guide][osos-readme].

## Classic emulation: useful, with a separate acceptance problem

The QEMU Classic target uses ARM926 and an S5L8702 machine model. Its documented
input example is `Firmware-24.9.1.2`, with decrypted OSOS and the resource partition
needed for fonts. The documented acquisition route uses emCORE and a physical
Classic's AES hardware. osos-lab offers a different potential acquisition path,
but matching its outputs to QEMU's input layout and boot assumptions still needs
verification. **No evidence reviewed establishes that current RepriseOS 2.0.5
boots correctly in this QEMU fork.** [QEMU setup][qemu-readme],
[Classic machine][qemu-machine].

Upstream reports menu navigation and guest rendering. Its playback notes also
report elapsed time stuck at 0:00, failed pause/resume, and failed track changes.
MP3 decoding is supplied by the Host. The optional `HLE_NP_OVERLAY` draws a
substitute Now Playing interface; it must be disabled for display research.
These limitations make timed artwork, queue replenishment and audio timing
unreliable conclusions until positive controls pass.
[Playback report][qemu-player], [overlay source][qemu-overlay].

The separate optional `HLE_NP` bootstrap contains fixed guest function, object,
buffer and semaphore addresses from the author's firmware investigation. It can
alter guest control state and invoke guest functions. Those addresses must not be
reused for an unqualified 2.0.5 image; start with this helper disabled and validate
any later intervention against the exact firmware. Unchanged firmware instructions
do not imply execution without Host intervention. [Bootstrap source][qemu-hle-np].

Available instruments include register/memory inspection, execution and peripheral
traces, GDB helpers, ATA traces, and captures. The documented Windows-hosted route
uses WSL Ubuntu 24.04 and produces a Linux executable; it is not a validated
native Windows build of the Classic target. [Build/test notes][qemu-build].

## Claims that need qualification

- **wInd3x Classic support:** the README labels Classic "6G" dump/decrypt and
  Haxed DFU experimental, but inspected device definitions and exploit dispatch
  register nano variants rather than a Classic kind. Do not convert that table
  into a verified Classic 7G command recipe. osos-lab's Classic implementation
  must be evaluated on its own evidence. [README][wind-readme],
  [device definitions][wind-devices], [dispatch][wind-dispatch].
- **Temporary access versus persistence:** Haxed DFU and custom firmware loading
  describe runtime boot mechanisms. wInd3x also has separate restore code that
  can repartition and write firmware. A temporarily booted OS can itself write
  storage. [Custom firmware command][wind-cfw], [restore implementation][wind-restore].
- **iPodWizard:** older firmware/resource editing code and raw writes do not
  establish support for later encrypted Classic images. Its current mirror is
  historical Win32/MFC source, without a validated modern Classic workflow.
  [Readme][wizard-readme], [write implementation][wizard-write].
- **Model catalogs versus emulator coverage:** siggifly's extensive identity and
  firmware catalog does not mean all listed models are emulated. The existing
  local Video lab cannot answer Classic behavior without a different machine.
  [Prior assessment][local-video], [Classic feasibility][local-classic].

## Existing local evidence and gaps

The October 11 experiment record documents a working Windows Video lab at
`C:\Users\JohnG\Coding\ipod-emulator` with artifacts at
`C:\Users\JohnG\Coding\ipod-emulator-lab`. It records menu navigation and controlled
artwork results for **iPod_20.1.3**, not Classic firmware. The checkout and lab
still exist. The checkout currently has additional local core edits beyond the
two GUI files recorded in that experiment; preserve them and capture fresh source
provenance before reusing its results. [Recorded experiments][local-experiments].

Targeted inspection of known research/artifact directories and common tool/input
locations found no ready Classic plaintext OSOS, Classic IPSW, or Ghidra installation.
This is a scoped observation, not proof that none exists elsewhere on the Host.
The prior Genius report remains evidence for the 120 GB Classic's RetailOS 2.0.1;
its referenced private capture directories were absent in this workspace inventory.
[Prior physical findings][local-genius].

Original iOpenPod's preserved firmware-restore research is useful historical context
but contains contradictory descriptions of OSOS and AUPD. Its extraction assumptions
should not be copied as an established Classic recipe. Current osos-lab source
separates the runtime image, updater-derived loader, and NOR identity explicitly.
[Preparation code][osos-firmware-cli], [manifest][osos-manifest].

## Relationship to iOpenPod

The current four boundaries describe filesystem/library management, not an existing
DFU or NOR-flashing contract. Keep experimental binaries, device captures and
private implementation plans in the ignored research area. Translate demonstrated
firmware behavior into documented format knowledge and small fixtures/tests.
Do not introduce an emulator dependency into ordinary Sync.
[System boundaries](../../CONTEXT.md#system-boundaries),
[source architecture](../source_architecture.md),
[Original baseline decision](../adr/0004-use-original-iopenpod-as-the-compatibility-baseline.md).

If direct firmware access becomes product scope, it needs an explicit architecture
decision. Storage would retain generic transport/device mutation responsibility;
iPod-specific image, identity and workflow policy must not leak into it. A
Filesystem Session or file-tree Backup Snapshot cannot be assumed to cover BootROM
DFU, NOR, or raw firmware partitions. The existing Storage Transaction contract
guarantees individually atomic file publication, not atomic flash replacement.
[Transaction contract](../adr/0029-publish-file-transactions-with-retained-recovery.md),
[canonical definitions](../../GLOSSARY.md#device-identity-and-storage).

## Reviewed revisions

| Repository | Commit |
| --- | --- |
| lgreitis/osos-lab | `d2c8e357d58591bdaa70bb6be9da191f489554a6` |
| daniel5151/clicky | `4575c278ceb424e7daae4e8f85a444a9c5509589` |
| davidmonterocrespo24/qemu-ipod-classic | `1c33be87c7e97b56053142ae9d7f0686feaed504` |
| siggifly/ipod-emulator | `d39e850ac07baa28abbdd8b00b77b834a757b5e1` |
| DavidBuchanan314/iPodWizard-mirror | `bf8360c348c0b9ef2f30b08b10ed536f4f7ef213` |
| freemyipod/wInd3x | `7c7c4d83c8b923f29e7559585b2cdbbf4e028045` |
| Xlinka/iPodReverseEngineering | `39b91fc999cbbacd27e56da3935a3cb4f166d77b` |

Context7 resolution was attempted for osos-lab, RepriseOS and wInd3x; no relevant
indexed documentation was returned. The findings therefore use first-party GitHub
documentation/source and the cited local experiment records. Upstream capabilities
remain upstream claims unless explicitly identified as local measurements.

[osos-readme]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/README.md
[osos-manifest]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/firmware/apple.json
[osos-profile]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/ghidra/profiles/firmware-2.0.5.json
[osos-old-profile]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/ghidra/profiles/classic6g-reva-2.0.1.json
[osos-analysis]: https://github.com/lgreitis/osos-lab/tree/d2c8e357d58591bdaa70bb6be9da191f489554a6/ghidra/analysis
[osos-docs]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/docs/README.md
[osos-runtime]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/docs/osos.md
[osos-firmware-cli]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-cli/src/firmware.rs
[osos-decrypt]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-cli/src/decrypt.rs
[osos-cli]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-cli/src/main.rs
[osos-usb]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-device/src/usb.rs
[osos-checks]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-device/src/lib.rs
[osos-patch-types]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/payload/patch.h
[osos-recipes]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-bundle/src/assembly/recipe.rs
[osos-patches]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/payload/patches/patches.c
[osos-boot]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/docs/boot.md
[osos-host]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/README.md
[qemu-readme]: https://github.com/davidmonterocrespo24/qemu-ipod-classic/blob/1c33be87c7e97b56053142ae9d7f0686feaed504/README.md
[qemu-machine]: https://github.com/davidmonterocrespo24/qemu-ipod-classic/blob/1c33be87c7e97b56053142ae9d7f0686feaed504/hw/arm/ipod_classic/ipod_classic.c
[qemu-player]: https://github.com/davidmonterocrespo24/qemu-ipod-classic/blob/1c33be87c7e97b56053142ae9d7f0686feaed504/wiki/20-classic6g-reproductor.md
[qemu-overlay]: https://github.com/davidmonterocrespo24/qemu-ipod-classic/blob/1c33be87c7e97b56053142ae9d7f0686feaed504/hw/arm/ipod_classic/ipod_classic_np_overlay.c
[qemu-hle-np]: https://github.com/davidmonterocrespo24/qemu-ipod-classic/blob/1c33be87c7e97b56053142ae9d7f0686feaed504/hw/arm/ipod_classic/ipod_classic_hle_np.c
[qemu-build]: https://github.com/davidmonterocrespo24/qemu-ipod-classic/blob/1c33be87c7e97b56053142ae9d7f0686feaed504/wiki/05-build-notes.md
[clicky-status]: https://github.com/daniel5151/clicky/blob/4575c278ceb424e7daae4e8f85a444a9c5509589/STATUS.md
[siggi-readme]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/README.md
[wizard-readme]: https://github.com/DavidBuchanan314/iPodWizard-mirror/blob/bf8360c348c0b9ef2f30b08b10ed536f4f7ef213/ReadMe.txt
[wizard-write]: https://github.com/DavidBuchanan314/iPodWizard-mirror/blob/bf8360c348c0b9ef2f30b08b10ed536f4f7ef213/iPodWizardDlg.cpp
[wind-readme]: https://github.com/freemyipod/wInd3x/blob/7c7c4d83c8b923f29e7559585b2cdbbf4e028045/README.md
[wind-devices]: https://github.com/freemyipod/wInd3x/blob/7c7c4d83c8b923f29e7559585b2cdbbf4e028045/pkg/devices/devices.go
[wind-dispatch]: https://github.com/freemyipod/wInd3x/blob/7c7c4d83c8b923f29e7559585b2cdbbf4e028045/pkg/exploit/exploit.go
[wind-cfw]: https://github.com/freemyipod/wInd3x/blob/7c7c4d83c8b923f29e7559585b2cdbbf4e028045/cmd/wInd3x/cmd_cfw.go
[wind-restore]: https://github.com/freemyipod/wInd3x/blob/7c7c4d83c8b923f29e7559585b2cdbbf4e028045/cmd/wInd3x/cmd_restore.go
[xlinka-tree]: https://github.com/Xlinka/iPodReverseEngineering/tree/39b91fc999cbbacd27e56da3935a3cb4f166d77b
[local-genius]: genius-generation-2026-10-24.md
[local-video]: ithmb/ipod-emulator-assessment.md
[local-classic]: ithmb/classic-emulator-feasibility.md
[local-experiments]: ithmb/ipod-emulator-experiments.md
