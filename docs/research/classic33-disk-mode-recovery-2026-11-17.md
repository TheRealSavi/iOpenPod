# Classic family 33: Apple Disk Mode recovery upload

Research date: 2026-11-17. Scope: offline inspection and bounded native emulation
of the Apple Disk Mode image embedded in family-33 2.0.1 AUPD, followed by an
exact comparison with retained plaintext decrypted from the installed NOR.
This investigation read retained files and issued no device commands.

## Result

Apple Disk Mode contains the same core `C6/90`, `C6/91`, `C6/92` upload sequence
and hidden raw-disk destination as the qualified normal RetailOS workflow. It
can therefore be the basis of an OSOS-independent stock recovery path, provided
Apple Disk Mode itself remains reachable. The installed image's entire
215,236-byte declared payload now matches the researched image byte for byte.
Disk Mode does not preserve the device-specific `hash` sector, and the traced
eject path does not establish the normal RetailOS automatic reboot behavior.
[Dispatch][dispatch], [start][start], [chunk][chunk], [end][end],
[normal-mode comparison][normal], [installed-image comparison][installedcomparison]

The appropriate recovery candidate is the retained, verified **complete device
firmware preimage**, which already contains that iPod's own `hash` data, sent
from a freshly identified forced-Disk-Mode connection. Uploading the pristine
package without replacing its device-specific sector is not equivalent to the
successful normal-mode reinstall. A separate explicit restart can be considered
after a complete verified upload; an interrupted upload must not be finalized,
ejected or restarted automatically. Physical Disk Mode vendor writes and the
complete recovery cycle remain untested. [Start][start], [end][end],
[prior preimage qualification][normal]

## Exact image and method

The input is the `0x348c4`-byte payload at offset `0xe7978` in
`Classic33FW/decrypted/legacy-plaintext/aupd-body.bin`:

- AUPD SHA-256:
  `dda3423b1ffecb5f638e8f66ccaecf67dd8c7ea33c01191130afb8b3fb036e41`.
- Embedded Disk Mode SHA-256:
  `6bf00b7ad65b08983f39f598a7a82bd2d009fe9f0d80abadddc3ed92f04a68d4`.
- File offset `0..0x730` maps to IRAM `0x22000000`.
- File offset `0x730..0x348c0` maps to DRAM `0x08000000`, length `0x34190`.
- DRAM BSS begins at `0x08034190`, length `0x10acc`.

The existing offline Disk Mode clock investigation establishes this extraction
and native relocation map. Four trailing bytes are part of the hash-qualified
input but are not in the two initialized runtime regions. A fresh ELF imported
only the runtime regions. The new exporter verified the concatenated initialized
bytes plus those trailing bytes against the full hash, and the read-only Ghidra
import was discarded afterwards. Its pseudocode types and names remain inferred;
instruction bytes control disputed interpretations. [Existing map checks][clock],
[new export provenance][provenance]

The saved installed NOR image has SHA-256
`bb34f00db4e81f2b5a5b367523c06f46f0fa91078ca9fb72fdfe9b38ebe1aa42`.
Its encrypted Disk Mode member begins at `0xcb530`, after the header at
`0xcb330`. A separate read-only device-key decryption retained the 215,248-byte
plaintext and a receipt reporting successful stored-SHA1 verification. Its
SHA-256 is
`1c12aad77028d2c3d306939a506594141e4d6576ad6c50a1231ef3acecfb75e4`.
The offline comparison independently verified the retained NOR hash, both input
hashes and the installed plaintext's SHA-1 against the actual saved header field.
[Retained receipt and comparison][installedcomparison]

All bytes at file offsets `0..0x348c4` match the AUPD embedded image exactly.
The installed plaintext has only twelve additional `0xff` bytes at
`0x348c4..0x348d0` for its 16-byte padded length. Hashing the embedded image
with that padding yields `0b837b00618115b7cbfc30d7b9e124155cd6f878`, exactly
the stored header digest. The earlier mismatch came from comparing the digest
with the unpadded image or with zero padding. There are no changed instructions,
data or installation fixups in the declared payload. Both initialized runtime
regions also match independently. [Reproducible comparison][comparisonscript],
[byte and region results][installedcomparison]

This completes installed-code identity qualification: the C6 handlers, adapter
selection, preservation behavior and eject paths below apply unchanged to the
retained installed NOR image. It does not establish successful vendor writes or
a complete physical recovery cycle.

## Wire operations and destination

The dispatch at `0x0800fe5c` recognizes opcode `0xc6`, subtracts `0x90` from
CDB byte 1, and selects entries 0 through 5. The useful handlers are:

| Operation | Handler | Relevant behavior |
| --- | --- | --- |
| `C6/90` | `0x08011cfc` | Open raw backend, reset byte cursor, set update flag |
| `C6/91` | `0x0801240c` | Decode BE16 count at CDB offset 2 and write blocks |
| `C6/92` | `0x080121d4` | Return success; no storage call |
| `C6/94` | `0x08012dd0` | Partition-changing path; excluded from recovery |
| `C6/95` | `0x08012c60` | Capacity reply; not required for this upload |

`C6/31` does not select a finalization handler in this dispatcher. An apparent
successful status for an unhandled subcommand is not evidence of an action.
[Dispatch][dispatch]

The mass-storage constructor `0x08013afc` puts `0x3f` in object field `+0x448`.
The chunk handler computes:

```text
destination LBA = 0x3f + byteCursor / logicalSectorBytes
new byteCursor = byteCursor + requestedBlocks * 4096
```

Zero requested blocks is treated as one. The sector size is obtained from the
backend; the physical read-only Disk Mode check observed 4096 bytes. Use the
existing bounded 32-KiB/eight-block chunk policy rather than exploiting the
zero-count interpretation. The start handler ignores the payload's advertised
total length, so the Host remains responsible for exact stream length and
firmware-area bounds. [Constructor][constructor], [chunk][chunk],
[physical sector capture][physical]

The chunk handler uses mode 1. Backend `0x08016c3c` selects object field `+8`
for nonzero mode, and field `+4` for normal mode. Constructor `0x08016ffc`
creates two adapters through `0x0801fa40`, passing remapping flag 1 for the
ordinary adapter and 0 for the upload adapter. Adapter initialization
`0x0801dccc` derives and installs the partition offset only when that flag is
nonzero. The raw adapter retains its initial offset zero; writer
`0x0801de94` adds that offset to the requested LBA. This qualifies the intended
upload destination as the hidden physical firmware area rather than Windows'
remapped FAT32 view. [Backend selection][backend], [backend construction][backendctor],
[adapter construction][adapterctor], [adapter initialization][adapterinit],
[adapter write][adapterwrite]

The chunk bounds check at `0x08010f20` consults the backend's overall capacity,
not a separately retained firmware partition end. The Host's qualified reserved
area limit is therefore still mandatory. Nothing here authorizes a partition
rewrite or ordinary Host raw writes. [Bounds check][bounds]

## Preservation and failure differences

Normal RetailOS saves one device-specific `hash` sector in its start handler
and restores it in its end handler. Disk Mode's start is only 64 bytes: initialize
the status, open the raw backend, reset cursor `+0x444`, and set flag `+0x44c`.
Its end is only 28 bytes and initializes a successful status. There is no
corresponding save/restore buffer or `hash` lookup in these paths.
[Disk Mode start][start], [Disk Mode end][end], [RetailOS evidence][normal]

Consequences for recovery:

- Prefer the complete verified preimage captured from this exact device. Its
  complete upload span preserves the device-specific record and all unchanged
  firmware companions by construction.
- If starting from an Apple package instead, construct and independently verify
  a stream containing the exact saved device-specific data before opening the
  upload session. Do not rely on Disk Mode to repair it afterwards.
- Acknowledged chunk failure advances the cursor after the attempted write,
  just as in normal RetailOS. Retrying that chunk in the same upload session
  can write it at the next location. Abort on ambiguity, retaining the journal.
- `C6/92` does not verify content or flush a special preservation buffer.
  Successful status cannot replace an independent read-back comparison.

These follow the actual handlers. The forced write failure was simulated by a
mocked write helper, never induced on the device. [Chunk][chunk],
[native handler vectors][vectors]

## Eject and restart

The standard `START STOP UNIT` handler is `0x080121f0`. With eject selected and
start clear, it reaches `0x08010190` and then `0x080121b8`. If the upload flag
at `+0x44c` is set, this marks `+0x44d` and unregisters the mass-storage service.
Its detach callback at `0x08016468` releases service resources and calls
`0x08024700(1)`. [Start/stop][startstop], [eject][eject], [detach][detach],
[storage callback][storagecallback]

That last routine selects a storage-driver callback at table offset `0x20`.
For the inspected tables, the targets are `0x0802bf78` and `0x08029a5c`; their
instruction windows construct a drive command with opcode `0xe0`. This is not
the explicit RetailOS pending-update reset routine documented in the normal
upload workflow. The direct `+0x44d` consumer used by RetailOS was not found in
this Disk Mode inspection. Do not claim that the same eject request reboots
Disk Mode automatically. [Callback table and instruction windows][callbackasm],
[RetailOS reset comparison][normal]

A deliberately requested Menu+Center restart after successful upload and
verification is the simpler candidate completion step. This remains conditional
on the retained NOR boot chain accepting the restored stock OSOS and on the
separate verification helper completing without depending on the modified
OSOS. This report does not qualify a NOR rollback or a new bootloader.

## What has been verified

The initial physical check demonstrated entry into Apple's Disk Mode, the same
selected device identity, `ForcedDiskMode=true`, 4096-byte sectors, and a
remapped FAT32 view that hides the firmware area from ordinary SCSI reads. It
did **not** exercise vendor data-out commands. The same Storage identity and
exclusive-session rules still apply to a new Disk Mode connection; an old
normal-mode session must not be reused. [Identity capture][identity],
[sector capture][physical], [Storage boundary][storage]

The new offline harness executes the real hash-qualified ARM handlers with
readiness, bounds, transport and storage endpoints mocked. Five vectors pass:

1. Start resets a nonzero cursor and sets the update flag.
2. Eight blocks target raw LBA 63, mode 1, and advance the cursor to 32768.
3. Three more blocks target LBA 71 and advance the cursor to 45056.
4. A mocked failed write still advances the cursor and returns failure status.
5. End returns success, preserves the cursor, and makes no storage call.

The test intentionally does not emulate controller completion, physical media,
USB disconnects or a successful boot. It supports the protocol comparison and
failure policy; it is not a physical recovery result. [Harness][harness],
[retained vectors][vectors]

A subsequent physical recovery upload has now completed through a fresh Storage
SCSI Session. It sent the exact 93,515,776-byte saved stock preimage, including
its original hash sector, in 2,856 acknowledged commands. The live identity,
`ForcedDiskMode=true`, capacity and visible partition sectors matched the saved
target. Library and identity files remained unchanged. No automatic eject or
restart was requested.
[Upload journal](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-disk-mode-recovery/upload.json)

After the user entered BootROM DFU, the independent acquisition helper verified
the complete written span in 23 ranges, with two device reads and device-side
SHA-256 for each. The result matches saved stock preimage SHA-256
`a0ff19a5f1eed0d883caf980d06e8c81e931ce623f8765a99ed19b5616715ab7`.
This establishes the Disk Mode write route on this device independently of OSOS.
It does not establish recovery after power loss or qualify another model.
[Full-span verification](C:/Users/JohnG/AppData/Local/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-disk-mode-recovery/raw-verification/verified-written-span.json)

[normal]: classic-stock-update-source-path-2026-11-17.md
[clock]: ../../../ipod-firmware-lab/scripts/check_classic33_disk_clock.py
[provenance]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/provenance.txt
[dispatch]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/0800fe5c.c
[start]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/08011cfc.c
[chunk]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/0801240c.c
[end]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/080121d4.c
[constructor]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/08013afc.c
[backend]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/08016c3c.c
[backendctor]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/08016ffc.c
[adapterctor]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/0801fa40.c
[adapterinit]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/0801dccc.c
[adapterwrite]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/0801de94.c
[bounds]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/08010f20.c
[startstop]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/080121f0.c
[eject]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/080121b8.c
[detach]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/08016468.c
[storagecallback]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-v3/08024700.c
[callbackasm]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-input/detach-callback-windows.asm.txt
[harness]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-input/check_handlers.py
[vectors]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-input/handler-vectors.json
[comparisonscript]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-input/compare_installed_disk.py
[installedcomparison]: ../../../ipod-firmware-lab/artifacts/classic33-disk-recovery-20261117-input/installed-disk-byte-comparison.json
[identity]: ../../../ipod-firmware-lab/captures/2026-11-17-classic-disk-mode-preflight/manifest.json
[physical]: ../../../ipod-firmware-lab/captures/2026-11-17-classic-disk-mode-scsi-sectors/manifest.json
[storage]: ../adr/0276-own-exclusive-scsi-sessions-in-storage.md
