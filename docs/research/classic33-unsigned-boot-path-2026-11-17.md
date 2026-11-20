# Classic33 unsigned OS boot path

Date: 2026-11-17. Scope: independent, offline review of the exact family-33
Classic Apple 2.0.1 bootloader and the `build-v5b` unsigned OS extension. This
review did not open or modify a Physical Device. It establishes source and binary
properties; it does not establish a successful physical boot or installation.

## Result

An explicit unsigned OS format can coexist with Apple's authenticated formats
and the already installed UKEY route. The extension must retain the native ROM
protocol's hardware/context wrapper, publish the BootROM success metadata, and
validate the file's actual read lengths before trusting its declared body size.
The proposed v5b implementation does these things. Its enlarged ROM module fits
by moving only later driver files into the existing padding space. Early startup
files must retain their absolute positions. [BootROM validator][bootrom-validator],
[ROM wrapper][rom-wrapper], [Bds loader][bds-loader], [v5b source snapshot][v5b-source].

The independently inspected v5b loader body has SHA-256
`fb0d5ebff7c97f3efb8de3e5b429e0b0bb698687b0aa7b1a8ef50d205c404f90`.
The complete volume contains 42 FFS files and 41 executable modules. Separate
Reprise extraction found exactly two changed executables, Bds and ROM; the other
39 are byte-identical to the original. The only changed FFS files are Bds, ROM,
and the padding file. All FFS header checksums, all enabled FFS body checksums,
and the firmware-volume header checksum pass. [Independent audit][audit],
[audit implementation][audit-script], [independent extraction][extracted].

## Qualified inputs

| Input | SHA-256 |
| --- | --- |
| Original 129,024-byte Apple loader body | `8d028296d20d7162eb109d062239ba510fe842510e006178040caacbabead1b8` |
| Original ROM PE | `b40292cb19cf8830172d3671d96cb4ae0eb720287ff37ef85698456aa0d29959` |
| Original Bds PE | `3098db1612edfc87180a52ec9fc9c5fbd8430e0e21d7afe19749f09dfec87e6a` |
| Captured BootROM | `69c087afc5753d7f0f11f09b141b372af753a854bc526673ea444c486d6003e4` |

The original modules are identified by their GUIDs in the [original module
inventory][original-modules]. The BootROM input is the retained
`captures/2026-11-17-classic-raw-probe/bootrom.bin` in the firmware lab. Addresses
below refer to these exact inputs, not another Classic release.

## Native file-size correction after v4

The v4 review incorrectly treated the file length returned to Bds as the raw
directory length. Exact native IpodFirmwareFS inspection found that Open at RVA
`0x560` first replaces the in-memory directory length with:

```text
virtual_length = (raw_directory_length + media_block_size + 64) & ~63
```

This rounds to the next 64-byte boundary even when already aligned. The custom
GetInfo routine at `0x890` returns that inflated length at output `+0x10`, and
the media block size at output `+8`. Bds receives them at `SP+0x54` and `SP+0x4c`.
Read at `0x67c` uses the same inflated length for its remaining-byte limit and
reports the actual requested/clamped count. Therefore v4's exact raw-length
equality rejects a valid custom header, and its original Bds allocation path
would also request extra bytes beyond the declared body. [Native FirmwareFS
Open][fs-open], [native GetInfo][fs-info], [native Read][fs-read].

V5b checks the native inflated length using the header-declared image length and
the supplied media block size, restricted to 512 or 4,096. Its new Bds allocation
bridge selects the already validated declared body size for custom images. The
existing exact actual-body-read check remains. Authenticated formats retain the
native allocation behavior. The raw image's directory length remains truthful;
the builder does not shorten it to compensate for Open. [V5b gate][v5b-gate],
[V5b bridges][v5b-bds].

The native transformation loses the original length's low six bits. The equality
therefore proves membership in the same rounded range, not exact equality to
the raw directory field. Memory bounds come from the declared size, the explicit
OSOS slot limit, the controlled allocation/read, and its exact actual-count
check; the CRC covers precisely those declared body bytes. The retained firmware
header's directory pointer is `0x4000`, while the directory starts at `0x5000`.
The native directory loader adds the media block size to that pointer, supporting
4,096 bytes for this boot path. The implementation nevertheless obtains and
validates the runtime value. [Native directory loader][fs-directory],
[V5b gate][v5b-gate], [V5b bridges][v5b-bds].

An independent native regression executes the original Open padding
instructions, full GetInfo and full Read, together with each candidate's native
Bds allocation instructions. Only EFI SetMem and physical DiskIo are mocked.
Across 20 cases covering both media block sizes, aligned/unaligned body lengths,
the actual `0xa06c90` body, and the maximum `0xa07800` body, v4 reproduces the
failure and v5b accepts and requests exactly the declared body. [Regression
receipt][fs-regression], [native regression implementation][fs-regression-script].

## Native validation and required success effects

The ROM header validator at module RVA `0x7fa` checks the header's `8702` prefix,
hashes its first `0x40` bytes, and checks the sealed digest at `+0x40`. Its key
selector is the third argument. The prior UKEY extension selects key 2 for
formats 1/2 and retains key 1 for Apple's normal path. [Native header
validator][rom-header], [prior UKEY gate][prior-gate].

The ROM body function at RVA `0x526` is more than signature verification. It
allocates and installs a BootROM context, changes interrupt and hardware state,
calls the validator, and restores that state. The v5b hook replaces only the
inner four-byte sequence at RVA `0x6b2`, leaving the wrapper intact. On entry to
that inner call, `r0` is the header, `r1` is the body, and `r3` is the original
BootROM validator. The original call uses mode 2. The new fourth argument keeps
the original callback available. [Wrapper disassembly][rom-wrapper-asm],
[v5b builder][v5b-builder], [compiled gate][gate-asm].

The BootROM validator at `0x200006dc` returns boolean 1 for success and 0 for
failure. Its success path publishes these fields:

| Destination | Value |
| --- | --- |
| `state + 0x30`, 32 bits | Header entry offset at `+8` |
| `state + 0x34` | Header byte 4 |
| `state + 0x35` | Header byte 5 |
| `state + 0x36` | Header byte 6 |

`state` is the pointer stored at absolute address `0x2203fff8`; the BootROM
literal at `0x20000b08` contains that address. The byte at `state + 0x37` must
remain intact. The unsigned body gate publishes these fields only after metadata
and body CRC validation succeeds. Its entry offset is constrained to zero,
because Bds ultimately branches to the allocated body base at RVA `0x4d2`, not
to body base plus the header entry field. The outer ROM wrapper translates the
inner boolean result into EFI success/error status. [BootROM validator][bootrom-validator],
[BootROM disassembly][bootrom-asm], [Bds disassembly][bds-asm],
[v5b gate][v5b-gate].

Skipping the BootROM crypto path also skips its SHA initialization routine at
`0x20001fe0`. That routine waits for SHA hardware, resets it, and marks the SHA
completion flag at context `+0x8c`. That flag is consumed by the SHA routines;
the custom path uses software CRC and does not submit SHA operations. This
supports omitting crypto initialization for the CRC path, but is not a hardware
boot proof. [SHA initialization][sha-init], [SHA completion consumer][sha-consumer].

## Explicit unsigned framing

The v5b gate recognizes only format byte `0x7f` as custom. Formats 1/2 retain the
UKEY header key 2 and BootROM body mode 1. Other formats go to the native
validation path; formats 3/4 retain normal Apple validation. A failed native
signature is never reinterpreted as permission to use the custom route.
[V5b gate][v5b-gate], [compiled gate][gate-asm].

| Header offset | Custom value or meaning |
| --- | --- |
| `0x00..0x06` | ASCII `87021.0` |
| `0x07` | `0x7f` |
| `0x08` | Entry offset 0 |
| `0x0c` | Body length, nonzero, at least 16, and divisible by 16 |
| `0x10` | IEEE CRC-32 of the body |
| `0x14` | Header length `0x800` |
| `0x18` | Updater family 33 |
| `0x1c` | Custom schema 1 |
| `0x20..0x2f` | Fixed 16-byte marker `IOPOD.UNSIGNED1` followed by NUL |
| `0x30..0x3f` | Zero reserved words |
| `0x40` | IEEE CRC-32 of bytes `0x00..0x3f` |

The body limit is `0xa07800`, derived from the existing `0xa08000` OSOS slot
minus its `0x800` header. The on-disk image length is header plus body; the native
virtual length follows the Open transformation described above.
These CRCs detect accidental corruption; they deliberately do not authenticate
the publisher. The header prefix is container metadata and does not replace
Apple's Firmware version or the independent Mod Platform Version.
[V5b gate][v5b-gate], [existing slot preparation][slot-preparation].

## Bds bounds and assembly bridges

The original Bds function allocates its body buffer from file metadata minus the
actual number of header bytes read. Its body validator consumes a different
length taken from the image header. Once the image is unsigned, checking only a
maximum header length is insufficient: a declared body longer than the file can
make CRC read past the allocation. Read success also needs an exact byte-count
check. [Bds loader][bds-loader], [Bds disassembly][bds-asm].

These offsets are relative to Bds's original stack pointer at the patched call
sites:

| Offset | Meaning |
| --- | --- |
| `SP + 0x14` | Actual header read count |
| `SP + 0x18` | Actual body read count, in/out parameter to Read |
| `SP + 0x20` | Header pointer |
| `SP + 0x24` | Uncached body pointer |
| `SP + 0x28` | Allocated body base used for final entry |
| `SP + 0x3c` | Selected ROM protocol |
| `SP + 0x4c` | Media block size from custom GetInfo |
| `SP + 0x54` | File byte length from metadata |
| `SP + 0x60` | Saved strict-validation argument |

The header bridge uses an eight-byte stack frame, requires an actual `0x800`
header read, and passes the virtual file length in `r3` as the header gate's
fourth argument. For custom format `0x7f`, it supplies the media block size in
`r2` and sets the saved strict argument to 1
before validation. Thus any malformed custom image fails instead of entering
Bds's legacy ImageManagerSecurity fallback. A short header also forces strict
failure. Ordinary full-length authenticated headers retain the old fallback
policy. [V5b Bds bridge][v5b-bds], [Bds disassembly][bds-asm].

The body bridge uses a 16-byte stack frame, preserves the selected callback in
`r4`, and requires actual body read count equal to the custom header's declared
length before invoking it. Formats other than `0x7f` retain the original body
callback. The common call site at RVA `0x49c` reaches both native and fallback
paths, so this preserves callback selection. Both bridges preserve callee-saved
registers and stack alignment. The original instructions after each hook set
condition flags from the return value, so the bridges need not restore incoming
flags. [V5b Bds bridge][v5b-bds], [compiled bridges][bridge-asm],
[Bds disassembly][bds-asm].

The patched ranges and targets verified in v5b are:

| Module | Patched range | New destination |
| --- | --- | --- |
| Bds | `0x3d0..0x3d9` | BL to header bridge `0x1480`, then three NOPs |
| Bds | `0x3de..0x3e3` | BL to allocation bridge `0x14b2`, then one NOP |
| Bds | `0x49c..0x4a1` | BL to body bridge `0x14c6`, then one NOP |
| ROM | `0x6b2..0x6b5` | BL to body dispatcher `0x1758` |
| ROM | Pointer at `0x13d4` | Thumb header gate pointer `0x1681` |

The bridges occupy 104 bytes of Bds's former 128-byte final debug section. The
ROM gate and CRC table occupy 1,604 bytes, with a `0x660`-byte aligned final
section. Both sections become executable `.mod` sections; image sizes and debug
directories are updated. The CRC table is addressed by Thumb ADR, avoiding an
additional absolute address relocation. Its 256 entries were independently
checked against polynomial `0xedb88320`. [Independent audit][audit],
[CRC source][crc-source], [compiled gate][gate-asm].

## Firmware-volume repacking constraints

The loader body is `0x1f800` bytes. Its firmware volume begins at `0x100`, has
length `0x1f700`, and starts its FFS files at `0x148`. Native DxeMain walks files
using their 24-bit size fields and eight-byte alignment. It enumerates by GUID,
skips padding type `0xf0`, and dispatches drivers using discovered entries and
dependency information. This supports shifting ordinary driver files after ROM
while preserving order and contents. [Native file walker][dxe-walker],
[native enumeration][dxe-enumeration], [native driver discovery][dxe-discovery],
[native dispatcher][dxe-dispatcher].

It does not permit moving everything indiscriminately. The initial raw vectors
target the fixed tail near body `0x1f7d0`; the SecCore file starts at `0x1f510`.
SecCore contains the absolute PreEfi entry pointer `0x22010545` at body offset
`0x1f7c0`. Therefore PreEfi's original position must also be preserved.
Independent comparison verifies this exact Classic33 literal and unchanged
prefix/tail bytes. [Independent audit][audit], [audit implementation][audit-script].

The v5b repacker keeps every file start through ROM at `0x13740` fixed. Bds's
recompressed file occupies the same eight-byte-aligned span as the original.
The repacker accepts that span directly; for smaller compressed versions it can
fill the difference with a valid Raw section inside the FFS file. Plain `0xff`
bytes inserted as a separate gap between files would be wrong
because the native file walker treats a blank file header as the end of the
volume. ROM expands by 1,480 padded bytes. Later drivers shift by exactly that
amount, and the padding file shrinks by the same amount, leaving SecCore at its
original address. [V5b repacker][v5b-repacker], [native file walker][dxe-walker],
[independent audit][audit].

An earlier offline candidate allowed Bds's shorter compressed representation to
move PreEfi by 16 bytes. That violated the absolute pointer constraint. The v5b
pinning and bounded Raw-section padding correct the issue; earlier candidates
are not the reviewed artifact. [V5b repacker][v5b-repacker], [independent audit][audit].

Native DxeMain checks the firmware-volume header checksum and FFS header
checksums. Function `0x168c` checks allowed file states, not the FFS body checksum.
The independent audit additionally verifies every enabled body checksum. For
files with the checksum attribute clear, the original input uses the older
fixed byte `0x5a`; the Go serializer emits `0xaa`. The native header checker
excludes the data checksum byte from its header sum, so this difference is not
a rejection condition in the inspected loader. [Native FV checksum][dxe-fv-checksum],
[native FFS header checksum][dxe-ffs-checksum], [native file-state check][dxe-state],
[pinned serializer][efi-file], [audit implementation][audit-script].

## Validation limits and next evidence

The separate Rust extractor successfully parsed/decompressed all 41 modules
from v5b, independently of the Go repacker. The Python audit independently walked
the FFS framing and compared bytes/checksums. These checks establish a bounded,
internally consistent candidate, not physical functionality. [Independent
extraction][extracted], [independent audit][audit].

Native execution tests should start at the actual patched Bds call sites, with
canaries around their real stack layout, and cover full/short headers, equal and
unequal file lengths, exact/short/overlong body reads, corrupted CRCs, bad custom
markers, strict and non-strict callers, and formats 1 through 4. Success should
publish only the documented BootROM fields; failures should not publish them.
This is a test recommendation derived from the inspected data flow, not a claim
that this review executed those tests. [Bds disassembly][bds-asm],
[v5b Bds bridge][v5b-bds], [v5b gate][v5b-gate].

The native ROM wrapper has a conditional post-success AES wait: if
`MMIO[0x38c00040] & 3` is nonzero, it waits for bit 0 of `MMIO[0x38c0000c]`.
The software CRC path submits no AES operation. V5b therefore adds a small body
dispatcher that retains the native wait for authenticated formats and bypasses
it only for format `0x7f`. It restores its saved `r4` and stack pointer, then
branches to native success status at `0x6d4` or failure status at `0x6d0`. Both
paths reach unchanged cleanup at `0x6d6`. The skipped interval contains only the
validator-result check and conditional AES completion wait; there is no other
validation or state publication in it. The original ROM function restores its
own saved return address, so the dispatcher's BL into these labels does not
alter the eventual return. [ROM wrapper disassembly][rom-wrapper-asm],
[V5b dispatcher][dispatcher-source], [compiled gate][gate-asm].

The implementation's retained native-test receipt records 1,668 passing cases
and 13 CRC vectors, including a 10,513,552-byte input. That receipt explicitly
states that legacy validator callbacks were mocked and makes no physical boot
or timing claim. This review read that receipt; the independent review also
executed the volume/module audit and the 20-case native FirmwareFS regression
described above. No fixed watchdog
deadline was established. The table-based CRC reduces CPU work relative to a
bit-at-a-time implementation, but boot latency still requires measurement on the
iPod. [Native-test receipt][native-tests], [CRC source][crc-source].

## Physical follow-up: installation and unsigned update

The following observations were obtained after the independent offline review
above, on the selected 120 GB Classic MB565, updater family 33, Apple 2.0.1.

The first v4 loader installed and booted the preceding UKEY-authenticated OS.
The unsigned 0.1.1 image then fell back to Disk Mode. Fresh VPD reported
`ForcedDiskMode=true`, and the user confirmed the screen. Native FirmwareFS
execution reproduced the padded-size mismatch described above; v5b fixes both
header qualification and the allocated/read body size. The correction was
installed without acquiring additional recovery copies.

The v5b one-use writer returned nonce `c78a41e2abf44a1fa98be6966f156b62`, success,
32 verified sectors and matching complete before/after NOR hashes. It programmed
only the 12 changed sectors. Its post-write scan confirmed that all bytes outside
`0x8000..0x28000` remained unchanged. The device then booted the already installed
unsigned 0.1.1 OS normally.

| Installed artifact | SHA-256 |
| --- | --- |
| Authenticated v5b loader envelope | `12439b3a55beec64b0c6fefb6db46144a4343e27a630343837118714d59a696f` |
| Complete NOR after correction | `a50244f8c72403085f08960ffb7f7424e3e2ee30aaa7291679744f09e923219e` |
| Unsigned 0.1.2 OS container | `8f6119b13055525c3506d012170809a615ac9a7df7bcc64cfb2eb94407e8e06a` |
| Complete 0.1.2 upload payload | `046cca42a513f76eae12e9633c0729ef951dbbb300e50ddee9f3c588a37ebad3` |

The subsequent 0.1.2 image was built entirely on the Host, with unkeyed CRCs.
All 2,856 normal-mode SCSI commands acknowledged the 93,515,776-byte upload,
followed by one acknowledged reboot request. No DFU session or device crypto was
used for this OS update. After a USB reconnect, fresh VPD reported normal mode,
the library/identity file digests matched the previous installation, and visible
capacity, MBR and boot-sector checks matched. Storage safely ejected the iPod.
The user then confirmed both Apple **2.0.1** and **Mod Version: 0.1.2-dev** on the
physical About page.

Small operation receipts are retained under this device's existing persistent
recovery directory: `2026-11-17-unsigned-loader-v5-report/record.json` and
`2026-11-17-unsigned-update-0.1.2/installation-verification.json`. The normal USB
driver is [classic33_unsigned_update.py][unsigned-update-driver]. The loader
installation driver is [classic33_unsigned_v5_install.py][v5-install-driver].
Both use Storage for device I/O and reject replay of consumed write operations.

Verification limits: this increment did not repeat the independent full NOR or
firmware-partition acquisition. Loader verification is the fresh helper's sector
comparison and full-NOR hashes; OS execution is established by normal boot and
the new physical version row, after the loader's body CRC check. Power-loss
recovery, other iPod models and general product installation remain unqualified.
DFU is still required for bootloader replacement or recovery; it is no longer a
requirement for ordinary custom OS composition and updates on this Classic.

[unsigned-update-driver]: ../../../ipod-firmware-lab/scripts/classic33_unsigned_update.py
[v5-install-driver]: ../../../ipod-firmware-lab/scripts/classic33_unsigned_v5_install.py
[bootrom-validator]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/200006dc.c
[bootrom-asm]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/200006dc.asm.txt
[rom-wrapper]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ROM-arm-export/00000526.c
[rom-wrapper-asm]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ROM-arm-export/00000526.asm.txt
[rom-header]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/ROM-arm-export/000007fa.c
[bds-loader]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/Bds-seeded-export/000002e6.c
[bds-asm]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/Bds-seeded-export/000002e6.asm.txt
[prior-gate]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/conditional_rom_gate.S
[original-modules]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/modules.json
[sha-init]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/20001fe0.c
[sha-consumer]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/BootROM-checked-export/20002298.c
[v5b-source]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-20261117/build-v5b/build.json
[v5b-builder]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-20261117/build-v5b/source/build_classic33_unsigned.py
[v5b-gate]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-20261117/build-v5b/source/gate.c
[v5b-bds]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-20261117/build-v5b/source/bds_bridge.S
[v5b-repacker]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-20261117/build-v5b/source/repack.go
[gate-asm]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-20261117/build-v5b/gate.asm.txt
[bridge-asm]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-20261117/build-v5b/bds_bridge.asm.txt
[crc-source]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-20261117/build-v5b/source/crc32.S
[dispatcher-source]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-20261117/build-v5b/source/native.S
[native-tests]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-20261117/build-v5b/native-tests.json
[slot-preparation]: ../../../ipod-firmware-lab/scripts/classic33_unsigned_images.py
[audit]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/audit-v5b.json
[audit-script]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/audit_v5b.py
[extracted]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/v5b-extracted/modules.json
[dxe-walker]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/DxeMain-export/00001364.c
[dxe-enumeration]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/DxeMain-export/000016ea.c
[dxe-discovery]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/DxeMain-export/0000093a.c
[dxe-dispatcher]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/DxeMain-export/000006fc.c
[dxe-fv-checksum]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/DxeMain-export/00001614.c
[dxe-ffs-checksum]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/DxeMain-export/0000163c.c
[dxe-state]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/DxeMain-export/0000168c.c
[efi-file]: ../../../ipod-firmware-lab/vendor/wInd3x/pkg/efi/file.go
[fs-open]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/FirmwareFS-export/00000560.asm.txt
[fs-info]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/FirmwareFS-export/00000890.asm.txt
[fs-read]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/FirmwareFS-export/0000067c.asm.txt
[fs-directory]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/FirmwareFS-export/00000284.c
[fs-regression]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/native-firmwarefs-v4-v5.json
[fs-regression-script]: ../../../ipod-firmware-lab/artifacts/classic33-unsigned-review-20261117/test_native_firmwarefs.py
