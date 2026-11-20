# Classic 33: a minimal modified Apple boot path

Research date: 2026-11-17. Target: the connected 120 GB Classic MB565,
updater family 33, Apple Firmware 2.0.1, serial `8P840FN62C7`. This investigation
performed **no device access or persistent writes** itself. It produced offline
loader, RAM-launch and bounded NOR-helper candidates. The orchestrating task
subsequently exercised both RAM launches, hardware UKEY signing, both NOR-helper
dry runs, Disk Mode stock recovery, and persistent bootloader installation.
The installed NOR passes independent full readback and a subsequent normal stock
boot. The modified OSOS upload was followed by normal USB operation and complete
firmware readback. The user confirmed the added About row renders correctly;
interrupted-write recovery remains unqualified.

## Finding

A modified OSOS cannot simply replace the encrypted, Apple-signed image on the
qualified normal boot path. The exact installed Apple loader requests GKEY header
authentication and BootROM verification mode 2; that mode accepts formats 3/4 and
verifies their RSA/X509 signature. The decrypted format-2 analysis file does not
establish stock acceptance. A narrow alternative is to modify one EFI module in
the existing Apple NOR loader to additionally accept device-UKEY-authenticated
formats 1/2, preserving the original formats 3/4 path. The candidate below does
that without replacing Apple's drivers or adopting the RepriseOS 2.0.5 bundle.
[Exact Bds loader](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/Bds-seeded-export/000002e6.c),
[exact ROM wrapper](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ROM-arm-export/00000526.c),
[captured BootROM validator](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/200006dc.c)

The first experiment was a RAM launch of the **unchanged exact Apple loader**,
then the conditional loader, with both disk and NOR still stock. Complete
non-destructive OSOS recovery qualification before replacing OSOS. NOR signing,
RAM reconstruction, Disk Mode recovery upload and persistent NOR writing now
pass physical checks. Stock boot from the installed loader also passes.
Interrupted-write recovery and unequivocal runtime identification of the earlier
RAM-only loader tests remain outstanding. The installed build now has physical
confirmation of its separate About version row.
[Stock workflow and recovery evidence](classic-stock-update-source-path-2026-11-17.md)

## Exact inputs

All addresses in the EFI tables below are module-relative offsets/RVAs; these
modules use matching raw section offsets. BootROM addresses are absolute.

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| Retained full NOR, before and after stock reinstall | 1,048,576 | `bb34f00db4e81f2b5a5b367523c06f46f0fa91078ca9fb72fdfe9b38ebe1aa42` |
| Installed, decrypted Apple loader body | 129,024 | `8d028296d20d7162eb109d062239ba510fe842510e006178040caacbabead1b8` |
| Exact captured BootROM | 65,536 | `69c087afc5753d7f0f11f09b141b372af753a854bc526673ea444c486d6003e4` |
| Extracted ROM EFI module | 5,600 | `b40292cb19cf8830172d3671d96cb4ae0eb720287ff37ef85698456aa0d29959` |
| Extracted Bds EFI module | 5,376 | `3098db1612edfc87180a52ec9fc9c5fbd8430e0e21d7afe19749f09dfec87e6a` |

The current full NOR backups are `before.nor.bin` and `after.nor.bin` under
`C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-preflash/`.
The older dump is `Classic33FW/captures/2026-10-26-dfu/nor.bin` in the lab. Its
decrypted `apple-loader-from-nor.bin` is byte-identical to
`Classic33FW/firmware/analysis-inputs/apple-loader.bin`, obtained from this
release's AUPD. The installed IM3 begins at NOR `0x8000`, has a `0x800`-byte header,
entry offset zero, and a `0x1f800`-byte body: the complete image occupies
`[0x8000, 0x28000)`. The header bytes after its first `0x50` bytes are all zero.
[Original extraction receipt](../../../ipod-firmware-lab/Classic33FW/captures/2026-10-26-dfu/nor-loader-report.json),
[new byte/checksum verification](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/verify_repacked_loader.py)

Local source pins used are `osos-lab` commit
`d2c8e357d58591bdaa70bb6be9da191f489554a6`, Rockbox commit
`10ec9bd530c852631ce126795cacf20e7578017f`, and wInd3x commit
`7c7c4d83c8b923f29e7559585b2cdbbf4e028045`. Ghidra exports were forced to
ARM little-endian v5t: Apple's PE machine field otherwise caused an incorrect
x86 import. Only the `ROM-arm-export`, `Bds-seeded-export`,
`ImageSecurity-export` and `BootROM-checked-export` directories are evidence;
earlier unsuccessful exports in the ignored artifact directory are not.
[Extraction inventory](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/modules.json),
[export script](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ExportBootModule.java)

## Authentication on this release

| Location | Observed operation |
| --- | --- |
| Bds `0x3d6..0x3d8` in `0x2e6` | Calls ROM protocol header validator with key selector 1 |
| ROM `0x7fa` | Checks the image prefix, hashes first `0x40` header bytes, seals the first 16 digest bytes through the requested hardware AES key, compares header `+0x40` |
| ROM `0x6b2..0x6b5` in `0x526` | Sets mode 2 and calls BootROM table `+0x74` |
| BootROM `0x200006dc`, mode 1 | Header seal with UKEY 2, accepts formats 1/2, optional format-1 decryption, body SHA-1/UKEY seal comparison at header `+0x10` |
| BootROM `0x200006dc`, other modes | Header seal with GKEY 1, accepts formats 3/4, bounds checks and RSA/X509 verification at `0x200055f0`, optional format-3 decryption |

The hardware-key definitions independently identify selector 1 as the model key
and selector 2 as the device-unique key. This is symmetric device authentication,
not possession of Apple's RSA signing key. A format-2 OSOS needs its body digest
seal and then its final header digest seal produced on the same device.
[Exact header validator](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ROM-arm-export/000007fa.c),
[BootROM modes](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/200006dc.c),
[Rockbox key/header definitions](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/firmware/target/arm/s5l8702/crypto-s5l8702.h),
[Rockbox signing implementation](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/firmware/target/arm/s5l8702/crypto-s5l8702.c)

There is a fallback through ImageManagerSecurity when Bds's strict argument is
zero. Its validator checks plain SHA-1 framing; however, Bds `0x872` derives the
strict argument from ChipId results and GPIO `0x400/0x401`. This investigation did
not qualify those production/development conditions on this device. It is not a
demonstrated stock-only route, and the normal-path result above is not a proof
that every possible stock-loader vulnerability has been excluded.
[Bds strict-mode selection](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/Bds-seeded-export/00000872.c),
[fallback validator](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ImageSecurity-export/00000220.c)

RepriseOS bypasses/replaces parts of the Apple handoff and stages its custom OSOS
through a RAM-backed file. Its documented 2.0.5 payload reservation at `0x08b33000`
and altered heap start do not qualify any 2.0.1 OSOS append/copy location. The
About-page work must use its separately qualified 2.0.1 startup-copy edits.
[RepriseOS boot design](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/docs/boot.md),
[RepriseOS handoff implementation](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/loader/apple/handoff/bds-combined.c)

## Conditional loader prototype

The prototype changes only ROM EFI GUID
`773641a1-cc51-41b7-b121-943bd7c5fc3f`, whose compressed FFS begins at loader body
offset `0x13740` and has original length 3533. Other EFI files, their offsets,
the volume header and the loader startup remain byte-identical.
[Builder](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/repack/main.go),
[verification result](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/repacked-loader-report.json)

| ROM module change | Purpose |
| --- | --- |
| Callback pointer at `0x13d4`: `0x7fb` to `0x1561` | Invoke the new Thumb header gate; existing HIGHLOW relocation already covers this pointer |
| Instruction pair at `0x6b2`: `02 22 98 47` to `00 f0 65 ff` | Replace `movs r2,2; blx r3` with a Thumb call to body gate `0x1580` |
| Header gate `0x1560..0x1571` | Only formats 1/2 override the requested header key with UKEY 2; call the original checker at `0x7fa` |
| Body gate `0x1580..0x1593` | Only formats 1/2 select BootROM mode 1; all other bytes retain mode 2 |
| Existing 128-byte `.debug` section becomes `.mod` | Same RVA/raw extent `0x1560..0x15df`; mark executable/readable, remove discardable, clear debug data directory |

Both gates preserve eight-byte stack alignment and R4, retain the arguments to
the original validators and propagate their return values. The modified PE is
recompressed with the pinned wInd3x EFI code. Unchanged recompression reproduced
the original FFS exactly. The changed compressed FFS is 3483 bytes; one alignment
byte and a 49-byte EFI Raw section preserve the original 3533-byte extent.
Header/data checksums were regenerated and verified. No other FFS moves.
[Gate assembly](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/conditional_rom_gate.S),
[PE patch and instruction checks](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/inspect_and_test_gate.py),
[EFI section serialization](https://github.com/freemyipod/wInd3x/blob/7c7c4d83c8b923f29e7559585b2cdbbf4e028045/pkg/efi/sections.go),
[FFS checksum serialization](https://github.com/freemyipod/wInd3x/blob/7c7c4d83c8b923f29e7559585b2cdbbf4e028045/pkg/efi/file.go)

The resulting plaintext `apple-loader-conditional-ukey.bin` is 129,024 bytes,
SHA-256 `ed92fedfe4a01087218b4e994aff26a3c4af6e2c50c9a2b3aeb259e51b490a8c`.
Its changed PE digest is
`37505a75f306a1ee93c2f8f9bbdbd92c5f0f0fc50a3c8851f1b5d13c2ec55bb5`.
An independent Rust extraction returned 41 modules; 40 are unchanged and the
remaining extracted ROM equals the candidate PE. The 1536 Unicorn cases cover
all 256 format bytes, header/body gates and three load bases. They validate the
instruction dispatch and relocated pointer, **not actual AES/RSA, Apple's PE
loader, hardware initialization or complete boot**.
[Gate results](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/conditional-rom-gate-report.json),
[independent comparison](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/verify_repacked_loader.py)

## Concrete RAM-first experiment

Rockbox's `launch_onb` loads the Apple body into IRAM0 `0x22000000`, retains its
IM3 header in IRAM1, disables external interrupts, synchronizes caches and jumps
to IRAM0. Its raw DFU packer runs raw code at `0x2200030c`, with a total download
limit of `0x20000` bytes. A 129024-byte loader body therefore fits alongside a
small independent trampoline; the 89440-byte acquisition helper plus loader
does not fit that limit.
[Apple handoff precedent](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/bootloader/ipod-s5l87xx.c),
[DFU limits](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/utils/mks5lboot/mks5lboot.h),
[raw DFU contract](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/utils/mks5lboot/README)

The new offline `ram_launch.S` and builder produce two RAM-only candidates:

| Candidate | DFU bytes | SHA-256 |
| --- | ---: | --- |
| `ram-launch-stock.dfu` | 130108 | `5eb12185a095c7ee5d87b6b09a3db9ebef95ddc637213600eab3590ca0eab330` |
| `ram-launch-conditional.dfu` | 130108 | `7b5ba12a8dbc72e8c01180d2db7e2daffd86de5e411b03406b27a55f810847ff` |

The 129328-byte raw payload masks IRQ/FIQ, cleans/drains caches and disables the
MMU and caches before rearranging IRAM. It reconstructs the exact original
`0x800`-byte header at `0x22020000` from its retained first 80 bytes, relocates its
64-byte copy tail to `0x22020800`, then copies the loader body from `0x2200043c`
down to `0x22000000`. Forward copying handles the overlap. It invalidates the
instruction cache/TLB and jumps to `0x22000000`; it does not return to DFU or
mount/write a filesystem. The unchanged Apple startup entry then establishes
its own stacks and initialization.
[RAM launcher source](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ram_launch.S),
[offline builder](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/build_ram_launch.py),
[build receipts](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ram-launch-build-report.json)

Four emulator cases verify exact final header/body bytes, control flow and writes
confined to those IRAM ranges. CP15 effects are mocked: cache behavior, DFU
execution, BootROM context and subsequent Apple startup remain physical checks.
Both generated DFU envelopes are byte-identical to the outputs of a native build
of unmodified pinned Rockbox `mkdfu.c` and `dualboot.c` called with `DFU_RAW`.
The wrapper `reference_mkdfu.c` performs file generation only and has no USB path.
[RAM-copy tests](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/test_ram_launch.py),
[test results](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ram-launch-test-report.json),
[reference packer wrapper](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/reference_mkdfu.c),
[upstream raw packer](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/utils/mks5lboot/mkdfu.c)

After independent review, the proposed physical sequence is: fresh exact-device
DFU identity/BootROM checks, explicit RAM-image download/manifestation through
the existing checked transport, observe normal boot, then compare device/library
identity and NOR against the retained baseline. Start with the stock candidate;
only after that boots, repeat using the conditional candidate. A USB handoff or
disconnect alone is not proof of boot. The ignored `ram-host` executable now
wraps the checked session, accepts only the two exact candidate hashes, pins the
serial/model/hardware/BootROM, and fsyncs preflight and intent receipts before
download. Its audited use of upstream `install_bootloader` is solely the
underlying download/manifestation transport; the accepted payloads have no
persistent-write path. That upstream method name alone does not describe which
operations the uploaded code will perform. Unit guards and both offline-only
image checks passed; no device was accessed by this research agent.
[RAM host source](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ram-host/src/main.rs),
[Current installation contract](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-device/src/install.rs)

## Signing, NOR writing and rollback work still required

The persistent candidate must be wrapped as a format-2 IM3, body signed with the
device's UKEY and then header signed, or retained as properly re-encrypted
format 1. For a format-2 candidate the complete `0x20000` NOR image changes representation
from encrypted to plaintext; a small logical patch is not a two-byte flash write.
The existing `fast_aes_key(..., decrypt=false, ...)` path is **an echo**, not an
encryption oracle. A new checked signing primitive must actually call BootROM
AES encryption `0x20001f64`, wait for completion, and validate returned 16-byte
seals. BootROM decryption is `0x20001f04`. Host SHA-1 can supply the digests, but
the device key itself should remain hardware-held.
[Existing AES payload](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/host/crates/reprise-device/src/payload.rs),
[exact BootROM signing calls](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/200006dc.c)

The ignored detached worktree `artifacts/classic33-mod-boot-20261117/ukey-lab`
now implements `Session::encrypt_ukey_block([u8; 16])` with a fixed zero IV and
key selector 2. It encrypts through `0x20001f64`, independently decrypts through
`0x20001f04`, compares all 16 input bytes, and returns ciphertext only after
successful DFU cleanup. It requires a previously successful checked Session.
The encryption payload differs from the established bounded UKEY-decrypt payload
only in that ROM call literal. A separate `Session::decrypt_ukey` exposes the
existing checked CBC-decrypt machinery for retained ciphertext; neither method
contains firmware policy or persistent writes. The device crate's offline suite
passed 61 tests, with two existing saved-ROM tests ignored. New cases cover
non-idle refusal, short responses, AES status failures, failed reverse comparison
and cleanup failure without retry. The subsequent hardware known-answer result
is recorded below.
[UKEY block method](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ukey-lab/host/crates/reprise-device/src/encrypt.rs),
[fixed encryption payload](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ukey-lab/host/crates/reprise-device/src/payload.rs),
[checked decryption API](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ukey-lab/host/crates/reprise-device/src/usb.rs),
[offline tests](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ukey-lab/host/crates/reprise-device/src/tests.rs)

Rockbox provides concrete SPI erase/write/readback primitives and `im3_write`,
which verifies the written range. Its dual-boot installer also signs on-device
and attempts original-loader restoration on failure. Those are implementation
precedents, not an already qualified arbitrary NOR writer for iOpenPod. The
current reprise API sends that installer, and the existing acquisition helper
intentionally rejects ATA writes.
[NOR read/write/readback](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/firmware/target/arm/s5l8702/norboot-s5l8702.c),
[installer signing and recovery](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/utils/mks5lboot/dualboot/dualboot.c),
[current acquisition guards](../../../ipod-firmware-lab/scripts/build_classic_acquisition.py)

A new Storage-owned mutation path should accept only the exact device and current
NOR digest, compare the complete original image before writing, constrain erases
and writes to `[0x8000, 0x28000)`, retain immutable original bytes, and stop on any
ambiguous transfer. Validate the freshly signed image in RAM before erasing.
Verify every affected block and independently read the full NOR afterward,
checking all bytes outside the loader span remain unchanged. A separate bounded
rollback helper should restore the original encrypted bytes without depending on
the patched loader. Power interruption during a boot-sector erase remains a
real unqualified failure mode; DFU availability is not itself a verified
data-preserving recovery workflow. Preserve SysCfg below `0x8000` and all NOR
resources/directory above `0x28000`.
[NOR layout and boot image bounds](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/firmware/target/arm/s5l8702/norboot-target.h),
[Storage ownership](../adr/0276-own-exclusive-scsi-sessions-in-storage.md)

Keep the disk stock during initial NOR installation/verification. Before the
later OSOS write, qualify a recovery route that does not need the modified OSOS:
prefer Apple's separate NOR Disk Mode and the already bounded vendor stream if
its exact handler and physical behavior are established. The same Bds policy
opens `disk`, `diag`, `aupd`, `osr3` and `osos` as distinct entries. The exact
embedded 2.0.1 Disk Mode image is AUPD plaintext slice
`[0xe7978, 0xe7978 + 0x348c4)`, SHA-256
`6bf00b7ad65b08983f39f598a7a82bd2d009fe9f0d80abadddc3ed92f04a68d4`.
Its existing runtime mapping is in the clock inspection script. Normal-mode
upload qualification must not be silently transferred to its separate handler.
The current NOR directory's `disk` entry points to `0xcb330`, with UKEY selector
2, a `0x200`-byte header and encrypted body length `0x348d0`. After the initial
digest comparison failed with zero padding, the orchestrating task decrypted
the installed member. It matches all 215236 embedded AUPD bytes exactly; the
remaining 12 bytes are `0xff`, not zero. The full decrypted SHA-256 is
`1c12aad77028d2c3d306939a506594141e4d6576ad6c50a1231ef3acecfb75e4`, and its
SHA-1 matches the stored
`0b837b00618115b7cbfc30d7b9e124155cd6f878`. No code or data fixups were found.
This establishes the installed handler's identity; it does not by itself prove
that a physical recovery upload succeeds.
[Installed Disk Mode comparison](../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-input/installed-disk-byte-comparison.json),
[comparison script](../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-input/compare_installed_disk.py)
If that route cannot be qualified, develop a bounded raw ATA preimage-restore
helper or an exact-release RAM-backed stock-OSOS boot path first.
[Bds entry selection](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/Bds-seeded-export/00000934.c),
[decoded names](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/repacked-loader-report.json),
[Disk Mode image and mapping](../../../ipod-firmware-lab/scripts/check_classic33_disk_clock.py)

Finally, derive the modified disk payload from the verified installed preimage,
preserving the existing AUPD bytes and applied bookkeeping. Bds `0x934` opens
`aupd`, reads its metadata, and when its leading status is zero changes it to one
before launching AUPD. The package's unapplied AUPD state therefore risks running
the stock NOR updater again. Preserve the already-applied flag and installed
padded length rather than reconstructing them from the pristine package. The
verified span, persistent record and raw layout remain constraints on every
candidate upload.
[Exact AUPD boot policy](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/Bds-seeded-export/00000934.c),
[verified installed differences and bounds](classic-stock-update-source-path-2026-11-17.md)

## RAM-launch observations supplied by the orchestrating task

The stock RAM launch at approximately `2026-11-17T10:47Z` and conditional RAM
launch at approximately `10:48Z` both passed the exact identity checks and
completed download/manifestation. Each retained receipt records 130112 transferred
bytes including the four-byte transport CRC, and deliberately records
`boot_verified=false`. After each launch the Classic returned as USB PID `1261`,
with family 33 / Apple Firmware 2.0.1 and unchanged SysInfo/SysInfoExtended hashes.
The user reported the normal Connected screen after the stock launch. The
conditional follow-up capture is timestamped `10:49:25Z`.
[Stock handoff receipt](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-ram-stock-boot/result.json),
[conditional handoff receipt](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-ram-conditional-boot/result.json),
[conditional normal-mode capture](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-ram-conditional-boot/normal-after/manifest.json)

This demonstrates a RAM-image handoff followed by a normal stock boot. No
runtime nonce identifies which loader completed that boot, so a watchdog reset
and fallback to the unchanged NOR loader cannot strictly be excluded. These
observations therefore do not prove the conditional format-1/2 gate executed,
nor authenticate a modified OSOS boot. The user-visible Mod Platform Version
will provide a later useful observation, but independent persistent readback
and recovery qualification are still necessary.

## Hardware signing result and bounded NOR recovery design

The orchestrating task exercised the new UKEY methods on the selected device.
Encrypting the known original NOR-header digest reproduced its original stored
MAC exactly. Each new body/header seal passed the reverse-decrypt comparison.
The signed conditional loader is 131072 bytes, SHA-256
`04fe69dd40faeed95d81181392e2aa8a4d0eb5a37620edc51afead44198c4c3f`; the signed
About-page OSOS is 10515600 bytes, SHA-256
`6172eace399f46a4822642b0d13787c78861bcb805805fc6d11babd281bf2581`.
The receipts explicitly record `installed=false`. These cryptographic checks
do not establish persistent boot or a successful flash write.
[Known-answer receipt](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-mod-signatures/known-answer.json),
[loader receipt](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-mod-signatures/loader.json),
[OSOS receipt](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-mod-signatures/osos.json)

The current DFU size limit need not force a streaming NOR writer. The exact
129024-byte loader contains an all-`0xff` run at `[0x1a700, 0x1f510)` of 19984
bytes. Omitting and reconstructing that verified run leaves 109040 body bytes;
the compact 80-byte IM3 header plus a small writer fit within the 130292-byte
raw-payload limit. This is the observed **2.0.1** run, not the RepriseOS 2.0.5
reservation. Rockbox's small dualboot installer runs in IRAM0 and holds the
contiguous `0x800`-byte header plus `0x1f800`-byte body in IRAM1
`[0x22020000, 0x22040000)`, providing a concrete workspace layout.
[Exact loader input](../../../ipod-firmware-lab/Classic33FW/firmware/analysis-inputs/apple-loader.bin),
[Rockbox installer workspace](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/utils/mks5lboot/dualboot/dualboot.c),
[installer linker layout](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/utils/mks5lboot/dualboot/dualboot.lds)

A separate rollback artifact can carry the exact original plaintext body in that
same compact form and the original 80-byte header. Reconstruct it in IRAM1,
encrypt the original body in place with device UKEY and zero IV, and require its
complete reconstructed encrypted-image digest to match the retained original
NOR span **before** erasing anything. Then restore and read back only
`[0x8000, 0x28000)`. This does not depend on the current NOR loader surviving a
partial write. The matching install artifact instead reconstructs the signed
format-2 candidate and verifies its complete known digest before programming.
Both artifacts are now implemented below; the reconstruction and read-only
paths pass physical dry runs, while programming remains unqualified.
[Original NOR representation and encryption helper](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/firmware/target/arm/s5l8702/crypto-s5l8702.c),
[retained recovery coverage](classic-stock-update-source-path-2026-11-17.md)

The captured BootROM provides these exact low-level SPI primitives:

| Address | Observed operation | Limit |
| --- | --- | --- |
| `0x20004b4c` | Transmit one byte on selected SPI port | Its TX-full wait is unbounded |
| `0x20004af4` | Receive one byte | Polls at most 100 times |
| `0x200018dc` | GPIO level; SPI0 CS uses `(0, 0, level)` | Must preserve transaction sequencing |
| `0x20004c7c` | Read status with command `0x05` and poll WIP | At most 100 status attempts, but underlying TX wait remains unbounded |
| `0x20004d60` | JEDEC `0x9f`, returns 24-bit ID | Helper independently observed this device as `0xbf258e` |
| `0x20004e5c` | NOR read `0x03` with 24-bit address | Existing acquisition uses this primitive |

No high-level BootROM sector-erase/program entry was qualified here. Rockbox's
SST25 implementation supplies the programming sequence: status write enable
`0x50`, write-status `0x01`, write-enable `0x06`, 4 KiB erase `0x20`, word AAI
program `0xad`, then write-disable `0x04` and protection restoration. Bound every
FIFO/WIP wait and verify chip identity before using it. Copying upstream loops
unchanged would not satisfy bounded failure handling. Full changed-sector erase
and byte readback are clearer than relying on an optimized partial-sector path.
Storage must own the resulting Host mutation transport and its exact-device
receipt lifecycle; a USB image handoff is not the flash completion receipt.
[BootROM TX](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/20004b4c.c),
[BootROM RX](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/20004af4.c),
[status polling](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/20004c7c.c),
[JEDEC reader](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/20004d60.c),
[NOR reader](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/20004e5c.c),
[Rockbox programming sequence](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/firmware/target/arm/s5l8702/norboot-s5l8702.c),
[SPI register access](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/firmware/target/arm/s5l8702/spi-s5l8702.c)

## Implemented NOR helpers and physical dry runs

The ignored `nor-helper` artifact directory contains the freestanding GPL-3.0
helper, ARM startup/linker files, builder, manifest/source snapshots and emulator
harnesses. It adapts the pinned Rockbox SPI/SST25 sequence without editing vendor
sources. SHA-256 and the DFU-return trampoline retain the pinned osos-lab source
and license headers. Each new manifest records all copied vendor hashes and the
helper, startup, linker and builder hashes. The physically exercised first
dry-run artifacts remain unchanged; their implementation snapshot is retained
as `dryrun-v1-source`.
[Helper implementation](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/helper.c),
[builder](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/build.py),
[preserved dry-run source](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/dryrun-v1-source/helper.c)

The orchestrating task launched rollback dry-run and then install dry-run through
Storage, following fresh exact BootROM/SysCfg checks. Both returned their pinned
nonce with phase 6, error 0 and `write_commands=0`. Before and after hashes were
the retained full NOR `bb34f00d…e1aa42`; the outside-boot hash remained
`fc9b6bca…5525c9`. Rollback reconstructed the exact original encrypted boot span
`170684be…27211c`, proving the full-body UKEY encryption and reconstruction on
this device. Install reconstructed the signed candidate `04fe69dd…98c4c3f`.
These receipts establish real SPI reads, SHA checks, reconstruction, AES and
DFU return, not erase/program behavior.
[Rollback dry-run receipt](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-nor-rollback-dryrun-report/record.json),
[install dry-run receipt](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-nor-install-dryrun-report/record.json)

Both runs reported JEDEC `BF 25 8E`, which identifies **SST25VF080B**, an 8-Mbit
SPI flash with 4 KiB sectors. Its manufacturer specifies `0x20` sector erase,
`0xad` AAI word programming, `0x05` busy polling and `0x04` AAI termination.
The `0x50`/`0x01` sequence permits status-register changes. The helper preserves
BP3/BPL, clears and verifies BP2..0 before programming, then restores and checks
protection plus cleared AAI/WEL. Physical-write builds reject every other JEDEC
ID. The emulator-only build instead uses a deliberately fictitious `DE AD BE`.
[Microchip DS20005045D, sections 4.3–4.4 and table 4-5](https://ww1.microchip.com/downloads/en/DeviceDoc/20005045D.pdf)

The helper occupies IRAM0, with payload/BSS below `0x2201e000`, a 4 KiB stack
reservation, and the receipt at `0x2201f000`. The reconstructed 128 KiB image
occupies IRAM1 `[0x22020000, 0x22040000)`. The write-v2 BSS ends are
`0x2201d960` for rollback and `0x2201d8cc` for install. Both DFU envelopes match
the native pinned Rockbox `mkdfu(DFU_RAW)` output byte for byte. They are smaller
than the `0x20000`-byte DFU image limit.
[Linker assertions](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/helper.lds),
[rollback symbols](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/rollback-write-v2/symbols.txt),
[install symbols](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/install-write-v2/symbols.txt),
[independent envelope wrapper](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/reference_mkdfu.c)

## Write-v2 bounds, receipts and recovery

Install requires exact original full NOR, original boot span, SysCfg region and
outside-boot hashes before writing. Rollback accepts a damaged boot span only
when SysCfg and every outside byte still match. Both reconstruct and verify
their target before status changes or erasure. Sector programming rejects any
unaligned address or address outside `[0x8000, 0x28000)`. It skips already equal
sectors, erases each changed 4 KiB sector, programs 2048 words, and reads the
whole sector back before proceeding. Order is `0x9000` through `0x27000`, then
the `0x8000` header sector last. This is **not atomic**: interrupted body writes
can invalidate the old header's body authentication before the header changes.
[Bounded implementation and preconditions](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/install-write-v2/source/helper.c)

All helper FIFO waits, WIP polls, AES polls and initial cache-clean attempts
have finite counters. A timeout or readback mismatch stops further programming
and returns an error. Cache-clean failure halts before NOR access. The reused
BootROM cold-init/DFU-return code includes its own hardware waits; it is not
claimed to be bounded in the same way. A failed mutation can leave protection
or AAI state changed. A fresh rollback helper waits for readiness and exits
inherited AAI before checking the JEDEC ID and retained region hashes. It does
not automatically retry the failed installation.
[Startup](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/start.S),
[rollback implementation](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/rollback-write-v2/source/helper.c),
[retained return code](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/vendor/return.c)

| Artifact | Bytes | SHA-256 | Receipt nonce |
| --- | ---: | --- | --- |
| `rollback-write-v2/helper.dfu` | 117052 | `394dd23d9f1f440b67f18f8f75453ffd93b5fad63d209df79a5031c262943217` | `922dd00d8d6841a4a8d28d8f52b2c9d9` |
| `install-write-v2/helper.dfu` | 116908 | `7e4a53b011851c883a2f485ae32098da3256b20ac98a6e299d51802f04b2efe6` | `473746e8f2c745eb9d4dd4412596ec4c` |

Rollback was built first. Manifests pin the original target full NOR hash above
and install's expected full NOR
`fc9c646a25401cc7cbb6f1c1d1cbb870bc962a7c21eb4e674d6380e979a928f7`.
[Rollback manifest](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/rollback-write-v2/manifest.json),
[install manifest](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/install-write-v2/manifest.json)

The receipt is 212 bytes at `0x2201f000`: magic `0x314e5249` at 0, version at
4, phase at 8, signed error at 12, nonce at 32, JEDEC at 64, mode at 68,
verified-sector count at 72, error-sector index at 76, command count at 80,
then four 32-byte hashes at 84/116/148/180 (before full NOR, target boot span,
after full NOR, outside boot). Install mode is 1; rollback mode is 3. Host
acceptance requires the exact nonce/mode/JEDEC, phase 6, error 0, 32 verified
sectors, exact expected hashes, and a separate complete NOR readback.
Successful USB download alone is insufficient.
[Receipt definition and population](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/helper.c)

Concrete recovery uses BootROM DFU, not the damaged NOR loader: re-enter DFU,
revalidate the pinned device and BootROM, launch only the pinned rollback image
through Storage, check its fresh receipt, and independently acquire/compare the
full NOR to `before.nor.bin`. Disk contents remain stock during this first NOR
step. This route's read/reconstruction/return portion is physically established;
erase/program recovery after a real interruption remains untested. It must not
be described as proven merely because the backup and helper exist.

## Offline writer verification and remaining limits

Nineteen dry-run ARM cases exercise hash guards, reconstruction, target
corruption, FIFO failures and return copying. Thirteen separate actual ARM
SHA-256 vectors match hashlib, including padding boundaries and a 4096-byte
input. Eleven tests exercise the exact BF258E write-v2 binaries against a
software SST25 model: install, rollback, partial-image recovery, inherited AAI,
readback mismatch, changed outside bytes, wrong JEDEC, denied unprotection,
denied WREN, erase timeout and failed protection restoration. The model records
all erase/program addresses and verifies header-last order. A first-sector
failure leaves the header untouched and prevents subsequent programming.
[Dry-run results](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/dryrun-tests.json),
[ARM SHA results](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/sha-tests.json),
[writer results](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/writer-tests-physical-images-v2.json),
[additional failure cases](../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/nor-helper/writer-tests-physical-images-v2-extra.json)

Writer emulation runs the compiled ARM SPI command path but substitutes full
NOR scans, SHA call boundaries and AES results; it does not model electrical
behavior, physical write timing, power loss or USB return. Real dry-run results
cover those read/reconstruction components separately. No claim of persistent
write success follows from combining these tests. The parent also found that
Apple's Windows driver permits a second handle despite `CreateFile` share mode
zero: the Host lease is cooperative, not an enforced exclusive OS device lock.

## Persistent installation observed

The one-use install-write-v2 helper ran through Storage after both dry runs and
full Disk Mode recovery qualification. Its retained receipt matches nonce
`473746e8f2c745eb9d4dd4412596ec4c`, mode 1, phase 6, error 0, JEDEC `0xbf258e`,
32 verified sectors and 65,668 write commands. Its original NOR, target boot span,
resulting full NOR and outside-boot hashes match the pinned plan.
[Helper receipt](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-nor-install-report/record.json)

A separate complete NOR acquisition then performed its 512-byte/509-byte
cross-check and matched all 1,048,576 bytes to the assembled `nor-mod.bin`.
The SHA-256 is
`fc9c646a25401cc7cbb6f1c1d1cbb870bc962a7c21eb4e674d6380e979a928f7`.
Everything outside `[0x8000, 0x28000)` remains byte-identical, including SysCfg
and the installed Disk Mode recovery image. Stock OSOS remained installed for
the next normal-boot check. The user then restarted normally; fresh locked SCSI
observations reported the selected Classic with Apple 2.0.1, and library files,
identity files, capacity and visible partition sectors matched the baseline.
This confirms persistent installation and stock boot, not recovery after an
interrupted write.
[Independent NOR acquisition](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-nor-install-report/nor-readback.json)
[Normal stock boot](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-nor-stock-boot/result.json)

The About-row firmware was then uploaded and booted to normal USB mode. A new
complete NOR acquisition after that boot again matched `nor-mod.bin` exactly,
with the same `fc9c646a...` full-image hash. The stock AUPD did not replace the
installed modified loader. Independent disk acquisition matched the entire
93,515,776-byte custom firmware and original raw partition table. Thus both
persistent images agree with the prepared build after its first normal USB
return; physical About rendering is recorded separately.
[Post-firmware NOR acquisition](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-mod-nor-readback/nor.json),
[Combined byte-verification receipt](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-mod-readback/installation-byte-verification.json)

The final normal boot passed fresh locked SCSI identity/layout checks and exact
library/identity file comparisons. Storage then safely ejected the device.
The user opened About and confirmed that Apple `2.0.1` and the new
`Mod Version: 0.1.0-dev` both appear and look correct. This is user observation of
the physical screen, not an agent-inspected screenshot. No other Classic or Nano
target is qualified by this result.
[Final installation verification](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-mod-final/installation-verification.json)

The Host consumes each helper nonce before transfer, including failed transfers.
A report must bind the same launch directory and completely acknowledged image
transfer. The two dry-run builds are retired; neither a new output directory nor
an old IRAM receipt permits another launch. The unused rollback build and its
complete sources are retained in the persistent device recovery directory.
[One-use orchestration](../../../ipod-firmware-lab/scripts/classic33_nor_install.py),
[Replay and receipt-binding tests](../../../ipod-firmware-lab/scripts/test_classic33_nor_install.py)
