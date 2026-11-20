# Classic hidden-firmware acquisition options

Research date: 2026-11-17. Target: Classic 120 GB, updater family 33, Apple 2.0.1,
product serial `8P840FN62C7`. This note records source inspection and offline ARM
disassembly only. No device command was issued by this investigation.

The later physical experiment qualified retained internal-RAM prefixes and
device-side digests, while an external-DRAM read stalled DFU. See the
[physical acquisition results](classic-stock-update-source-path-2026-11-17.md#physically-verified-recovery-material-and-upload-preparation)
for the implemented route and verified recovery preimage. The options below
retain their original proposal status.

## Finding

The shortest implementation route appears to be a small, hash-bound modification
of the **existing prebuilt Reprise helper fixture**. Retain its hardware/DRAM/ATA
initialization, replace its application body after geometry capture with bounded
raw reads, and use its existing return-to-DFU routine. Read the retained buffer
through Reprise's existing DFU memory reader. This avoids rebuilding Rockbox and
adding a new USB protocol, but remains a proposal until the modified helper and
buffer retention are physically qualified.

Ordinary stock READ(10) does not expose the hidden area in either tested mode;
the native vendor update writer supplies no independently qualified read-back.
See the [stock-update investigation](classic-stock-update-source-path-2026-11-17.md).

## Available prebuilt inputs

The pinned `osos-lab` checkout is commit
`d2c8e357d58591bdaa70bb6be9da191f489554a6`. Its
`usb-helper/tests/fixtures/upload.dfu` is a complete 89,440-byte image, not a
synthetic tiny fixture. SHA-256:

```text
07af9b210c620c482e80fbeadf8cd02db15ec998beff8cd98fe8acf11228af13
```

Its descriptor identifies schema 3, storage inspection, the exact Classic BootROM
hash `69c087afc5753d7f0f11f09b141b372af753a854bc526673ea444c486d6003e4`, nonce
offset 88,736, configuration offset 88,756, and cold-init offset 76,804. The image
predates some current source additions; **addresses below belong only to this
fixture hash**, not to current builds or the latest release.
[Fixture](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/tests/fixtures/upload.dfu),
[descriptor](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/tests/fixtures/manifest.json)

The current published v0.3.1 release also supplies a prebuilt helper. Its
270,059-byte `repriseos-classic.zip` was downloaded and independently hashed as
`a990c7deeec323c5d57cde01d9459d5aca505180a66819daf26d39c771be9000`, matching
GitHub's asset digest. Its manifest selects the 96,512-byte helper blob
`27e5af1d05af25bcb1ab8830b13840174a84b730a50d33dc70e683e783f92015` and descriptor
`6b99e11615b90e4b66685334a24902bb6b1412878287bcec66aafd815c7f5868`. The ZIP
contains blobs and manifests, **no ELF or linker map**. No signature-verification
claim is made here, and nothing from that ZIP was executed.
[v0.3.1 release](https://github.com/lgreitis/osos-lab/releases/tag/v0.3.1),
[downloaded archive](../../../ipod-firmware-lab/artifacts/classic-acquisition-fixture-20261117/repriseos-classic-v0.3.1.zip)

The unmodified helpers implement file upload and bounded layout diagnostics;
neither offers an arbitrary raw-sector download command. Their original
build path expects ARM GCC 9.5.0, a pinned Rockbox checkout, configure, and make.
The CI artifact contains `build/releases/`, not the intermediate ELF/map.
[USB protocol](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/usb.c),
[build](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/build.py),
[CI](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/.github/workflows/firmware.yml)

## Exact fixture memory map and patch seams

The IMG1 header is 2,048 bytes. Its ARM startup copies the body to
`0x22020800..0x22035d60`, then enters relocated code. Consequently:

```text
body offset = runtime address - 0x22020800
IMG1 file offset = runtime address - 0x22020000
body SHA-256 = f2939bfc22ce6ff2c800989b3e8f36e6cbb3c7a5fb3b4543bfe069018f26793d
```

The startup's literals at body offsets `0x88`, `0x8c`, and `0x90` establish its
copy end, copy start, and relocated entry. Its BSS clearing range is
`0x08800000..0x0889be60`. Function names in the table are inferred from the
instruction sequences, call sites, and upstream source; they are not recovered
ELF symbols. Exact original bytes and a complete ARM disassembly are retained.
[Sites and bytes](../../../ipod-firmware-lab/artifacts/classic-acquisition-fixture-20261117/sites.json),
[complete disassembly](../../../ipod-firmware-lab/artifacts/classic-acquisition-fixture-20261117/disassembly.asm)

| Purpose | Runtime address | IMG1 file offset | Evidence |
| --- | --- | --- | --- |
| Main | `0x22020f28` | `0xf28` | Startup branch; nonce, battery, hardware, and ATA initialization |
| ATA initialization | `0x2202dbc0` | `0xdbc0` | Main calls at `0x22020ff4`; result stored in record |
| Storage geometry | `0x2202d0e4` | `0xd0e4` | Called at `0x2202100c`; main copies sector bytes and 64-bit count |
| Proposed replacement entry | `0x22021034` | `0x1034` | Immediately after main records phase 3 and geometry |
| Main literal pool | `0x220216b8` | `0x16b8` | Used by initialization; must remain intact |
| Raw read wrapper | `0x2202d680` | `0xd680` | Layout reader invokes twice; `r0:r1` LBA, `r2` count, `r3` buffer |
| Raw transfer core | `0x2202d3cc` | `0xd3cc` | Fifth argument selects read/write; checks disk capacity |
| Write permission guard | `0x220216e4` | `0x16e4` | Transfer core calls it for every nonzero write argument |
| Raw write wrapper | `0x2202d800` | `0xd800` | Read-modify-write wrapper and write=1 core calls |
| Return to DFU | `0x22020ee0` | `0xee0` | Disables interrupts, copies return blob, flushes caches, calls it |

Use at most the `0x660` bytes in `0x22021034..0x22021694` for a replacement stub;
the stub must branch explicitly to the return routine and never fall through
into the original file/USB path. The first original 16 bytes at that hook are
`292da0e30500a0e1c54c00ebc730e0e3`. The unchanged earlier code already checks
hibernation, battery voltage of at least 3,600 mV, and successful ATA initialization.

Make the write rejection structural in the image, not merely a host promise.
The guard's first eight bytes are `80309fe5f0402de9`; replacing them with
`0000a0e31eff2fe1` encodes `mov r0,#0; bx lr`. The core calls this guard at
`0x2202d474`; a false result returns failure before the hardware transfer. As a
second gate, the write wrapper's first eight bytes `f74f2de964919fe5` can become
`0000e0e31eff2fe1` (`mvn r0,#0; bx lr`). Require the complete original image hash
and expected bytes before applying either change. These gates do not substitute
for testing the stub's bounds and control flow.

## Sector units and capture bounds

This driver does **not** promise 512-byte logical sectors. Initialization obtains
the logical size from ATA IDENTIFY (or CE-ATA's exponent), defaults to 512 where
appropriate, and accepts up to 4096. The fixture stores the logical byte count
at `0x08858860`, total native sectors at `0x088598b8`, and its physical-sector
multiplier at `0x22035cda`. `storage_get_info` copies these fields to main's local
structure, and main records the first two in `0x2201f000` before the hook.
The 512-byte IDENTIFY buffer is at `0x08858660`; retain it for model, drive serial,
and geometry evidence. The read wrapper handles unaligned physical sectors
internally. These findings follow the fixture instructions and the corresponding
[Rockbox driver](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/firmware/target/arm/s5l8702/ipod6g/storage_ata-6g.c).

The raw core tests `sector + count <= total_sectors`, but its entry does not
establish positive count and overflow-safe addition for arbitrary callers.
The replacement must independently require a positive bounded count, supported
power-of-two logical size, no addition/multiplication overflow, and an output
range wholly outside helper code, BSS, stacks, return code, and result records.
Use observed native sector size to convert byte ranges. The physical image header
is expected near byte 258,048 from the separate Apple writer analysis; initially
reading the first MiB covers that location for both 512- and 4096-byte geometries.
Actual raw partition/header observations must establish the final backup extent.

## Return and retained-buffer qualification

The fixture return routine copies 1,596 bytes from `0x22032b84` to `0x22010000`,
flushes/invalidate caches, and calls the copied code. The existing DFU return
record is 64 bytes at `0x2201f000`, including nonce, phase, status, geometry,
battery, and return count. Reprise's host checks the nonce after USB re-enumeration.
[Record layout](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/record.h),
[return assembly](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/return.S),
[return C](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/return.c)

The return path replays the verified BootROM reset instructions at offsets
`0xc0..0x284`, clears IRAM1 `0x22020000..0x22040000`, reestablishes stacks, and
enters only the USB branch of DFUBoot. It avoids boot-media selection. The
host `read_memory` already reads up to 64 KiB per call as 512-byte replies and
cleans the DFU transfer state afterward. The existing code does not itself
establish that arbitrary DRAM data survives the reset fragment.
[Cold-init relocation](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-device/src/upload/image.rs),
[DFU memory reader](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-device/src/dfu.rs)

A bounded initial test can read a sector into the unused IRAM area starting
`0x22014000`, copy it to a chosen DRAM buffer, return, and compare both copies on
the Host. This IRAM range is below the explicit clear region and above the return
code, but buffer use still needs execution validation. If successful, enlarge
gradually and compare device-side checksums with Host hashes, followed by a
second physical read of the capture. A successful DFU return alone is not proof
that the requested disk bytes were read or retained correctly.

### Captured BootROM clock findings

The subsequently retained 65,536-byte BootROM has the expected SHA-256
`69c087afc5753d7f0f11f09b141b372af753a854bc526673ea444c486d6003e4`.
Its actual reset instructions settle an important part of the retention question:
the unmodified return sequence **disables both the SDRAM access clock and its
refresh clock**. Attempting a DFU memory read from DRAM in that state is therefore
not a qualified acquisition path; an ensuing USB timeout would be consistent with
the CPU waiting on inaccessible memory, though the timeout alone does not prove
which request failed.
[Captured ROM](../../../ipod-firmware-lab/captures/2026-11-17-classic-raw-probe/bootrom.bin),
[reset disassembly](../../../ipod-firmware-lab/artifacts/classic-acquisition-fixture-20261117/bootrom-cold-init-disassembly.asm)

| ROM instruction | Register write | Relevant effect |
| --- | --- | --- |
| `0x13c` prepares value; `0x140` stores | `CLKCON0` / `0x3c500000 = 0x80000000` | Sets SDRAM-disable bit 31 |
| `0x228` prepares value; `0x22c` stores | `CLKCON4` / `0x3c500010 = 0x80008000` | High half is `CG16_RTIME = 0x8000`, disabling its output |
| `0x270` prepares value; `0x274` stores | `CLKCON0 = 0x80001000` | Finishes with SDRAM still disabled |

Rockbox explicitly defines `CLKCON0_SDR_DISABLE_BIT` as bit 31, locates
`CG16_RTIME` at `CLK_BASE + 0x12`, defines its disable bit as bit 15, and describes
that clock as the source of the MIU's DRAM refresh signals. No direct MIU register
write occurs in the replayed ROM range `0xc0..0x284`; the helper's preceding return
wrapper changes `MIUCON[2:0]` for address-zero remapping.
[Register definitions](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/firmware/export/s5l87xx.h),
[clock source description](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/firmware/target/arm/s5l8702/clocking-s5l8702.h),
[return wrapper](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/return.S)

A candidate preservation experiment changes only three value-producing
instructions in the **relocated RAM copy**, leaving the captured BootROM intact:

| ROM offset | Offset within relocated cold-init slot | Original word | Replacement word | Replacement instruction |
| --- | --- | --- | --- | --- |
| `0x13c` | `0x7c` | `e3a00102` | `e3a00000` | `mov r0,#0` |
| `0x228` | `0x168` | `e59f032c` | `e3a00902` | `mov r0,#0x8000` |
| `0x270` | `0x1b0` | `e59f02fc` | `e3a00a01` | `mov r0,#0x1000` |

The replacement at `0x228` keeps the low-half audio clock disabled and enables
the high-half refresh clock. Do not change its shared `0x80008000` literal:
other stores also consume that literal. Validate the exact BootROM hash and
original instruction words before producing a modified relocation; PC-relative
LDR immediates change during ordinary relocation, so the original ROM words are
not the expected words after relocation. Four offline Unicorn traces, covering
both strap branches with and without these three changes, produce the intended
final clock values. This checks instruction encoding and control flow, **not**
physical DRAM timing, retention, or subsequent DFU behavior. Prefer the retained
IRAM approach below when it can establish the complete write preimage.
[Trace script](../../../ipod-firmware-lab/artifacts/classic-acquisition-fixture-20261117/check_cold_init_clocks.py),
[trace results](../../../ipod-firmware-lab/artifacts/classic-acquisition-fixture-20261117/cold-init-clock-checks.json)

### On-device hashing without DRAM retention

The fixture already contains ordinary software SHA-256 routines. These can hash
raw sectors while the helper and DRAM remain active, then leave only the digest
and acquisition record in retained IRAM before returning to DFU.

| Function | Runtime address | ARM arguments | First 16 original bytes |
| --- | --- | --- | --- |
| `sha256_init` | `0x220223d8` | `r0 = context` | `2020a0e310402de914109fe50040a0e1` |
| `sha256_update` | `0x22022400` | `r0 = context`, `r1 = data`, `r2 = byte count` | `f0472de90240a0e1d022c0e10060a0e1` |
| `sha256_final` | `0x220224ac` | `r0 = context`, `r1 = 32-byte digest` | `f0412de9207090e5245090e53f3007e2` |

The context occupies 104 bytes with 8-byte alignment: eight state words at offset
0, a 64-bit byte counter at offset 32, and a 64-byte tail at offset 40. The block
routine is at `0x22021fa0`; these routines use the fixture's normal memory-copy
and memory-fill functions and do not access device registers.
[Source and ABI](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/sha256.h),
[implementation](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/sha256.c)

Offline execution of the **original fixture machine code** in Unicorn 2.1.4
matched Python's SHA-256 for 28 vectors: empty input, `abc`, padding/block
boundaries, split and zero-length updates, 64 KiB, and one million bytes in
16 updates. Context/output canaries and stack balance also passed.
[Executable check](../../../ipod-firmware-lab/artifacts/classic-acquisition-fixture-20261117/check_sha_functions.py),
[hash results](../../../ipod-firmware-lab/artifacts/classic-acquisition-fixture-20261117/sha-function-checks.json)

This enables a conditional shortcut: retain the device-specific header/directory
and hash-record sectors through IRAM, construct the proposed complete preimage
using the already retained exact Apple payload, and compare its full-span hash
against independently read raw device sectors. Only an exact match over **every
byte that the update may modify**, with explicit offsets and padding, establishes
that reconstructed file as a recoverable preimage. A mismatch requires acquiring
the differing bytes; a digest alone is not a firmware backup. Hash the bounded
region in manageable chunks, propagate every ATA error, retain the full byte
count and range, and independently repeat the device read before relying on it.

## Other routes considered

emCORE already has raw-sector USB debug command 28 and a Host
`storage_read_sectors_md` method. However, its normal initialization also mounts
filesystems, and the monitor exposes write, flash, and filesystem mutation
commands. Running its unmodified installer or ordinary disk mode would introduce
more unqualified behavior than the narrow helper patch. Its public temporary
core directory currently lists zero-byte images. This is useful source material,
not a ready read-only fallback.
[Monitor implementation](https://github.com/freemyipod/freemyipod/blob/master/emcore/usb/usbdebug.c),
[Host method](https://github.com/freemyipod/freemyipod/blob/master/emcore/tools/libemcore.py),
[initialization](https://github.com/freemyipod/freemyipod/blob/master/emcore/init.c),
[temporary image listing](https://files.freemyipod.org/tmp/emcore/)

The acquisition path is temporary RAM execution. It does not require installing
RepriseOS, Rockbox, emCORE, or a custom NOR bootloader. It also does not by itself
complete the stock-update workflow: before the first flash, retain the verified
hidden firmware/persistent-record captures, bind the stock image and transfer
plan to the selected device, persist update progress, and qualify post-write
read-back and normal boot.
