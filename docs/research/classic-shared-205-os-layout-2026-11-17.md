# Shared Classic 2.0.5 OS image: layout and About port

Research date: 2026-11-17. This is offline binary and native-source analysis.
No device access, persistent writes or physical cross-family boot tests occurred.
The later [physical family-33 trial](#physical-family-33-trial) below is a separate
qualification of the exact candidate produced from this analysis.

## Inputs

The common source is Apple's family-38 2.0.5 package. The retained extraction
and hardware decryption evidence identify these exact inputs:

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| IPSW | See retained package | `80f974edea54ae4c9b659578a0c4d74438ffd94b8270944ec0cfc8f10e90eb2d` |
| `Firmware-38.9.0.5` | 95,735,808 | `9450c5b51f8785d41c1eef041eac3c7a521d0b325d730f591759b49d041086aa` |
| Raw decrypted OSOS body | 10,632,448 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |
| Prepared OSOS with 0x800-byte header | 10,634,496 | `660eb6ff5f498bb1a75e85f1f9921bf0c753525a8bca9b4fa47ed260e5ad0f1e` |

The prepared input is the upstream `osos.bin` framing of the same body; do not
compare its digest with the raw body's digest. [Retained extraction][extraction],
[runtime map][runtime], [upstream input pins][pins].

## Common firmware layout

Replacing only the existing OSOS slot is too small on families 24, 33 and 35.
Using the complete 2.0.5 firmware-member layout provides its larger resource bank
and OSOS slot together, without changing the disk's partition table. The
firmware directory itself is at firmware-relative `0x5000`; the header's
`0x4000` offset has an additional block bias. The following are the exact stored
directory offsets, not raw-disk addresses:

| Source family | Resource length | OSOS offset | AUPD offset | Hash offset | Member bytes |
| --- | --- | --- | --- | --- | ---: |
| 24 | `0x4e00000` | `0x4e07000` | `0x5780000` | `0x589e000` | 92,930,048 |
| 33 | `0x4e00000` | `0x4e07000` | `0x580f000` | `0x592d000` | 93,515,776 |
| 35 | `0x4e00000` | `0x4e07000` | `0x5824000` | `0x5942000` | 93,601,792 |
| 38 | `0x5000000` | `0x5007000` | `0x5a2d000` | `0x5b4b000` | 95,735,808 |

The known family-33 device's firmware partition is 201,326,592 bytes, so the
common member fits there. Actual capacity must still be checked for every
selected device; an original package's size is not evidence of its partition's
full capacity. No new physical capacities were acquired for 24, 35 or 38.
[Physical layout evidence][layout].

A full common composition should preserve the pinned 2.0.5 resource bytes,
place the common unsigned OSOS into the latest OSOS slot and update its length,
and explicitly suppress stock AUPD execution. If future custom OSOS growth
exceeds that slot, move following entries with a reviewed layout builder rather
than truncating the image or overwriting the next entry. There is ample space
in the known 192 MiB partition, but available capacity is not itself a validated
relocation algorithm. [Exact member][member], [directory parser][parser].

## AUPD must not replace the custom loader

The pristine package has an AUPD status of zero at directory offset `0x5058`.
The shared Bds implementation opens AUPD, reads its metadata, and if the leading
status is zero, writes one and launches AUPD. That signed Apple updater can
replace NOR contents, including the custom loader. The common composition must
make AUPD ineligible for automatic execution before first boot. Setting its
status to the already-applied value one is supported by the native branch and
the existing physical family-33 capture. It does not require modifying or
re-signing AUPD. [Bds entry selection][bds], [earlier policy analysis][aupd].

The family-33 post-update directory differs from its package at `0x5058`
(status 0 to 1), `0x5060..0x5061` (AUPD length to `0x11d900`), and
`0x50b0..0x50b1`. Only the status change is the observed Bds execution gate.
Do not copy the complete family-33 directory or its other values into the
common 2.0.5 member. [Retained directory][directory].

## Device-specific persistent record remains outside the shared OS

Normal USB update start (`C6/90`) attempts to save the device's `hash` record;
update end (`C6/92`) restores it. Therefore a shared input image does not imply
that all installed firmware-partition bytes are identical: the device-specific
persistent record must survive. This does not alter the shared OSOS executable
or resources. [Preservation behavior][update].

The family-33 old hash location falls inside the larger 2.0.5 OS span, so a
cached old directory pointer would be dangerous. The existing native export
resolves this at the application-code level: `FairPlay_WritePersistentRecordSlice`
at `0x08043498` calls `0x08054d3c`, which invokes the raw-device preparation
function, resolves the firmware partition through `0x08092510`, then calls
`0x080583b0`. That last function reads the current firmware header and directory
through device read operations and resolves the requested entry from those
bytes. It does not retain the old hash offset between update start and end.
This source path supports moving hash with the common layout; it is not a new
physical cache-coherence or interrupted-update test. [Record writer][hashwrite],
[entry resolver][resolve], [directory reader][lookup], [partition reader][partition].

## Exact native About port

The prior 2.0.1 About recipe ports to the following 2.0.5 addresses. Matching
masked only ARM branch immediates; every other word in each stated function
window matched. The candidate was unique in the raw body. This establishes
instruction-shape correspondence, not execution of its new branch targets.
Full raw-body hashing and preimage checks remain mandatory in the builder.
[Reproducible comparison][compare], [comparison results][results].

| Operation | 2.0.5 runtime address | Compared bytes |
| --- | --- | ---: |
| `UI_InitResourceProviders` | `0x081c7e68` | 184 |
| Override initialization call | `0x081c7ea8` | Instruction bytes `14 28 fd eb` |
| `ResourceBank_InitOverrides` | `0x08111f00` | 28 |
| `ResourceBank_SetResource` | `0x08111e20` | 224 |
| `MenuItems_RegisterResourceType` | `0x08194df0` | 216 |
| Startup region copy | `0x22004700` | 156 |
| Copy return replacement site | `0x2200479c` | 12 |
| Native BSS clear | `0x22004808` | 60 |
| `Platform_GetHeapRegion` | `0x0804b448` | 48 |
| Heap-region lower-bound literal | `0x0804b478` | Word `0x08b3b1b0` |
| Runtime heap-init wrapper | `0x0807c030` | 24 |
| Runtime heap lower-bound literal | `0x0807c048` | Word `0x08b3b1b0` |

The two other occurrences of the BSS-end word, at `0x220030f4` and
`0x0802dcf8`, belong to the exception-stack arrangement and must remain unchanged,
as in the prior recipe. The native startup copies these regions:

| Raw body source | Runtime destination | Bytes |
| --- | --- | --- |
| `0x0` | `0x22000000` | `0xaf98` |
| `0xaf98` | `0x08000000` | `0xa182e0` |
| `0xa23278` | `0x08a182e0` | `0xa84` |
| No file bytes | `0x08a18d64` | `0x12244c` zeroed BSS |

Thus BSS ends at `0x08b3b1b0`. A small payload at aligned `0x08b3c000` with
heap lower bound advanced to `0x08b3d000` follows the same one-page reservation
strategy as the earlier About payload. Raw body offsets become prepared-file
offsets by adding `0x800`. The raw body's initialized regions total
`0xa23cfc`; the body itself is `0xa23d00` bytes. Append after the complete
input, retaining the four trailing bytes. The return-site original bytes are
`04 00 9f e5 70 40 bd e8 10 ff 2f e1`. [Runtime map][runtime],
[comparison results][results], [prior native recipe][previous].

The latest About View is **`0x0dad0b2a`**, at raw offset **`0x8395f8`**
(prepared `0x839df8`), length 892, SHA-256
`75b8f4e3817f6cbb993baaf16466260bd04550afa4ca5a5970e4f966395f9da1`.
Its six child IDs are `0x0dad0b2b` through `0x0dad0b30`, and their source IDs
are 1672 through 1677. The first three static sources resolve to Serial Number,
Model, Version; their paired values use the existing native providers. Both
columns use Y origins 153, 171, 189. [Resource catalog][banks],
[comparison results][results].

Clone the latest View's third label and value, retain the original six bindings,
and use the previous four-row positions 144, 162, 180, 198. The latest template
has different font/flag words as well as different IDs, so copying the old
2.0.1 View is incorrect. Reusing the latest native View ID allows the existing
type-registration function to enumerate it and index the extra children.
The compiled hook should call the three latest native addresses above, replace
View `0x0dad0b2a`, and preserve the independent Mod Platform Version field.
The initial analysis did not execute a candidate. The subsequent independent
audit below exercises its compiled relocation and hook paths.
[Previous implementation contract][previous],
[instruction comparison][results].

## Independent candidate validation

The common **0.2.0-dev** build was independently checked after the source
comparison. The adapted harness uses fixed 2.0.5 addresses from this research,
not imports of the production builder. It executes the actual compiled payload
with Unicorn 2.1.4. [Harness][test], [machine-readable receipt][tested].

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| About-patched prepared OS | 10,636,104 | `ac189240290394f0c86920bd5b8d32ce273c18901fd09df42798cc91117d0660` |
| Common unsigned OSOS | 10,636,112 | `c42321b6be13da43f14af5f5f4ae723d96a28e1a38f54b1c6a30d1f3f2e75486` |
| Common firmware member | 95,735,808 | `05b1d49671a42f190ed7f8bbd62c2f8b38e54749cb8261c39904dbef851ecff4` |
| Compiled About payload | 1,608 | `97c6430da7a975c644361f114c0f7d2bcef6fc2cb0076e0f03ee494e778289fe` |

The native copy routine, patched return and appended copy stub complete from
both staging addresses `0x08000000` and `0x09000000`. All three initialized
regions match the candidate, native BSS clearing completes, and the payload
survives. The callee-saved registers, stack, return address and surrounding
canaries remain unchanged. Both heap literals advance to `0x08b3d000`; both
exception-stack literals remain at `0x08b3b1b0`. [Execution results][tested].

The compiled resource hook calls the latest native addresses in the required
order. The harness substitutes native allocation/registration callbacks and
clobbers caller-saved registers to test the hook's ABI. It captures five
resources and verifies eight text children: the six original children preserve
every byte except their intended Y positions, and the two additions resolve to
**Mod Version** and **0.2.0-dev**. A second run changes only the independent
version variable to equal-length **0.3.0-dev** and observes the changed value.
The six newly used IDs do not collide with indexed resource or View-child IDs
in the original 2.0.5 banks. [Hook and resource results][tested].

An independent byte comparison permits only the four known native patch sites,
the three prepared-header length words, and the appended payload. The common
OSOS has exactly that patched body plus eight alignment bytes, valid header and
body CRCs, common target `CLSC`, and schema 2. Its complete firmware composition
changes only `0x5038..0x503b` (OSOS length), `0x5058..0x505b` (AUPD status), and
`0x5007000..0x5a2cfff` (OSOS slot). Every other byte, including resource, AUPD
and package hash-record bytes, matches the pinned original member. The unused
OSOS slot tail is zero-filled, with **5,296 bytes** remaining. [Image audit][tested].

These checks establish the compiled relocation, BSS, hook ABI, resource
construction, image framing and bounded offline composition. They do not run a
complete Apple OS, the native resource allocator, physical display, USB update,
device-specific hash restoration, or power-loss recovery. Cross-family hardware
boot and installation readiness remain separate qualifications.

## Physical family-33 trial

On 2026-11-17, the user authorized installation on the previously studied
120 GB Classic 6.5, model MB565, physical hardware `0x00130100`. The new lab
driver `scripts/shared_classic_physical.py` uses the application bootloader
installer and Storage transports. Its 17 offline tests cover exact transfer
coverage, invalid source observations, changed image rejection and incomplete
receipt rejection. Product Restore/Update buttons remain download-only.

The installed inputs are the exact common artifacts audited above:

- Shared marked bootloader body, version **2.0.0**:
  `9cb983b4bc8b5707074cdc06ce4a3634a78694ddea3449adb7727c6c4449100c`.
- Shared OSOS, Apple **2.0.5**, Mod Platform Version **0.2.0-dev**:
  `c42321b6be13da43f14af5f5f4ae723d96a28e1a38f54b1c6a30d1f3f2e75486`.
- Common firmware member, **95,735,808 bytes**:
  `05b1d49671a42f190ed7f8bbd62c2f8b38e54749cb8261c39904dbef851ecff4`.

The application matched the live SysCfg and authenticated installed loader,
generated the per-device bootloader header, and launched its packaged NOR writer
once. The returned nonce-bound report verified all 32 boot-span sectors, the full
result and unchanged bytes outside the boot span. The existing retained original
NOR was reused through a Host hard link; no new recovery image was acquired.
After a manual restart, live USB still reported healthy family 33 / Apple 2.0.1,
establishing that the shared loader booted the prior unsigned 0.1.2-dev firmware.

The complete common member was then sent once through the existing normal-mode
`C6/90`, `C6/91`, `C6/92` update sequence, followed by the reviewed reboot command.
There was no OS signing, second DFU entry, partition edit or write retry. After
boot, fresh live USB reported family **38**, Apple **2.0.5**, normal mode, and the
same 196,608 KiB firmware-partition capacity. Family 38 is the shared OS's reported
identity; the physical hardware remains family 33. The visible MBR, boot sector
and capacity matched the retained baseline. The iTunesDB, ArtworkDB, Photo
Database and both saved SysInfo files retained their pre-trial hashes.

Windows confirmed safe ejection. The user then confirmed that Settings > About
shows both **2.0.5** and **0.2.0-dev**, and that text, clickwheel/menu navigation
and headphone song playback work normally.

Operation receipts remain in persistent Host application data under
`firmware/recovery/<selected-serial>/2026-11-17-shared-205-trial`:
`preflight.json`, `loader.json`, `loader-boot.json`, `upload.json`, `reboot.json`,
`normal-boot.json`, `eject.json` and `physical-result.json`. The application's
`firmware/bootloader/<selected-serial>/operation.json` contains the original
nonce-bound writer result. The trial saves hashes and receipts, not additional
device-image copies.

This establishes installation, normal boot, live USB identity, basic display,
clickwheel and headphone playback on this one MB565. It does not establish other
Classic revisions, every peripheral or media feature, power-loss recovery, or
a second unsigned update while already running 2.0.5. No independent full
firmware-partition or post-OS-update NOR acquisition was performed. The relocated
device-specific hash record was not independently read back. These limits are
separate from the writer's verified bootloader readback and successful OS boot.

[extraction]: ../../../ipod-firmware-lab/Classic38FW/evidence/extraction.json
[runtime]: ../../../ipod-firmware-lab/Classic38FW/evidence/runtime-map.json
[pins]: https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/firmware/apple.json
[member]: ../../../ipod-firmware-lab/Classic38FW/firmware/Firmware-38.9.0.5
[parser]: ../../../ipod-firmware-lab/scripts/extract_classic_ipsw.py
[layout]: classic-stock-update-source-path-2026-11-17.md
[bds]: ../../../ipod-firmware-lab/artifacts/classic33-mod-boot-20261117/Bds-seeded-export/00000934.c
[aupd]: classic33-modified-boot-path-2026-11-17.md
[directory]: ../../../ipod-firmware-lab/captures/2026-11-17-classic-firmware-directory/sectors.bin
[update]: classic-stock-update-source-path-2026-11-17.md#preservation-and-retries
[hashwrite]: ../../../ipod-firmware-lab/artifacts/classic-update-backend14-20261117/08043498-FairPlay_WritePersistentRecordSlice.c
[resolve]: ../../../ipod-firmware-lab/artifacts/classic-update-backend14-20261117/08054d3c-FUN_08054d3c.c
[lookup]: ../../../ipod-firmware-lab/artifacts/classic-update-backend14-20261117/080583b0-FUN_080583b0.c
[partition]: ../../../ipod-firmware-lab/artifacts/classic-update-backend14-20261117/08092510-FUN_08092510.c
[compare]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-layout-20261117/analyze.py
[results]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-layout-20261117/analysis.json
[previous]: classic33-about-resource-extension-2026-11-17.md
[banks]: ../../../ipod-firmware-lab/artifacts/preferences-classic-resource-banks-20261107/banks.json
[test]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-layout-20261117/test_about205.py
[tested]: ../../../ipod-firmware-lab/artifacts/classic-shared-205-layout-20261117/emulation.json
