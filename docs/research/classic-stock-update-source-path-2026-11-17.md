# Classic stock update: prior art and protocol boundary

Research date: 2026-11-17. Scope: reinstall an unchanged, exact-family Apple
release while preserving the existing data volume. Source inspection was followed
by standard SCSI reads, temporary read-only DFU/RAM acquisition, and one successful
stock 2.0.1 vendor upload on the selected family-33 Classic. No repartition command
was issued. The later physical-results sections distinguish demonstrated behavior
from the earlier source-derived hypotheses and remaining recovery questions.

## Finding

The useful starting point is Apple's vendor SCSI firmware stream, followed by
qualification against the connected Classic's own implementation. RepriseOS
provides useful device identity, backup, and transfer patterns, but its installer
installs a different boot chain. It is not a stock-update implementation.
Rockbox's `ipodpatcher` raw-partition writer is also not the right starting point
for the currently exposed Classic volume. These conclusions follow the concrete
paths below; they do not establish that the entire Nano recipe is safe on a
Classic.

The exact initial target is updater family **33**, Apple **2.0.1**. The current
read-only capture reports `UpdateMethod=3`, `MaxFWBlocks=16`,
`FWPartSize=196608`, `AutoRebootAfterFirmwareUpdate=true`,
`ForcedDiskMode=false`, and `CorruptDataPartition=false`. `FWPartSize` is in KiB:
the native producer multiplies a count of 4096-byte sectors by four. Thus the
observed reserved area is **192 MiB**. The earlier 512-byte-unit interpretation
was incorrect and has been removed from the preparation code. These observations
do not establish successful installation.
[Capture](../../../ipod-firmware-lab/captures/2026-11-17-classic-update-preflight/manifest.json)

## What RepriseOS actually does

The current installer was inspected at commit
`96536d38d089ef3a198fe1cedd8522c6ce646153`; its Cargo manifest pins `osos-lab` to
`0575ef9abc62d7a0bb081279ea8551033b3969ae`. Its workflow validates a checked USB
identity, inspects the existing bootloader and storage, saves NOR backup evidence,
prepares Apple inputs, and builds modified artifacts.
[Entry point](https://github.com/lgreitis/repriseos-installer/blob/96536d38d089ef3a198fe1cedd8522c6ce646153/src-tauri/src/install.rs),
[dependency pin](https://github.com/lgreitis/repriseos-installer/blob/96536d38d089ef3a198fe1cedd8522c6ce646153/src-tauri/Cargo.toml)

The transfer writes ordinary FAT32 files `/cfw-loader.bin` and `/osos-cfw.bin`,
plus optional theme files, through its uploaded helper. If the installed custom
bootloader matches, it keeps NOR and requests a restart. Otherwise it sends a
NOR bootloader installer. Completion distinguishes verified disk files from a
bootloader handoff whose NOR completion has not been read back.
[Transfer](https://github.com/lgreitis/repriseos-installer/blob/96536d38d089ef3a198fe1cedd8522c6ce646153/src-tauri/src/install/transfer.rs),
[completion reporting](https://github.com/lgreitis/repriseos-installer/blob/96536d38d089ef3a198fe1cedd8522c6ce646153/src-tauri/src/install/job.rs)

The firmware preparation decrypts OSOS and AUPD from its selected **2.0.5** base,
verifies cached plaintext, then assembles its custom artifacts. That cross-Classic
custom firmware policy does not qualify Apple's family-38 stock package for an
unmodified family-33 update. For this task retain family 33's complete original
firmware member, not RepriseOS's plaintext OSOS or custom file layout.
[Preparation](https://github.com/lgreitis/repriseos-installer/blob/96536d38d089ef3a198fe1cedd8522c6ce646153/src-tauri/src/install/firmware.rs)

## What wInd3x provides

Both the lab pin `7c7c4d83c8b923f29e7559585b2cdbbf4e028045` and inspected current
upstream `fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60` define Nano 3–7 device
descriptors, but **no Classic descriptor**. Its README advertises experimental
Classic capability. The executable selector and catalog-family mapping take
precedence over that general claim; do not run its unmodified restore command
against this Classic. In particular, Nano 3 and Classic can share a DFU PID.
[Device table](https://github.com/freemyipod/wInd3x/blob/fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60/pkg/devices/devices.go),
[README](https://github.com/freemyipod/wInd3x/blob/fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60/README.md)

Its source implements these vendor commands:

| Operation | CDB length | Wire contents after opcode `C6` | Data phase |
| --- | --- | --- | --- |
| Start | 16 | `90`, kind byte, original byte length as big-endian u32, zero padding | None |
| Chunk | 10 | `91`, 4096-byte block count as big-endian u16, zero padding | Host to device |
| End | 16 | `92`, zero padding | None |
| Repartition | 16 | `94`, encoded size, zero padding | None |
| Finalize | 16 | `31`, zero padding | None |

Firmware kind is `0`; separate bootloader kind is `1`. The complete upload pads
the final data to 4096 bytes and uses 32768-byte chunks. This is the upstream wire
encoding, **not a validated Classic recipe**.
[Update commands](https://github.com/freemyipod/wInd3x/blob/fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60/pkg/usbms/ipod.go),
[CDB encoding](https://github.com/freemyipod/wInd3x/blob/fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60/pkg/usbms/scsi.go)

The restore command sends original WTF and recovery images only when beginning in
the corresponding DFU stages. Its disk-mode branch always uploads firmware.
`--full=false` omits repartitioning and the separate bootloader upload; `--full`
performs both, except the separate bootloader is skipped for Nano 3. The command
nevertheless warns that data will be lost. Omitting `94` is necessary for our
scope but is not, by itself, a media-preservation guarantee.
[Restore state machine](https://github.com/freemyipod/wInd3x/blob/fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60/cmd/wInd3x/cmd_restore.go),
[flag defaults](https://github.com/freemyipod/wInd3x/blob/fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60/cmd/wInd3x/main.go)

The firmware upload input is the IPSW's complete firmware member. OSOS-only
extraction belongs to separate payload kinds. Its transport directly drives USB
mass-storage Bulk-Only Transport; Windows native SCSI pass-through is a separate
implementation requirement.
[Extraction](https://github.com/freemyipod/wInd3x/blob/fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60/pkg/cache/cache.go),
[USB transport](https://github.com/freemyipod/wInd3x/blob/fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60/pkg/usbms/usbms.go)

## Why the precise Classic mode matters

The family-33 RetailOS dispatcher has now been inspected independently in the
local Apple image. At `0x080d6cb0`, vendor opcode `C6` dispatches only subcommands
`90`, `91`, `92`, `94`, and `95`; **it does not dispatch `31`**. Consequently the
recovery-mode finalization sequence above must not be copied blindly into the
ordinary connected RetailOS update. The hash-bound decompiler output and assembly
are retained for further qualification; inferred function names are not Apple's
original source identifiers.
[Dispatcher](../../../ipod-firmware-lab/artifacts/classic-update-dispatch-20261117/080d6cb0-FUN_080d6cb0.c),
[source hashes](../../../ipod-firmware-lab/artifacts/classic-update-dispatch-20261117/export-source-hashes.json)

Chikuma's first-party research corroborates a hidden firmware area, vendor SCSI,
and AUPD's later NOR-update role, but explicitly calls the ordinary host update
sequence inferred rather than captured from iTunes. Retrieved versions disagreed:
one still says the vendor payload is unknown; another claims decoded NOR disk-mode
handlers, including a `90` data phase and destructive `94` behavior. That `90`
claim conflicts with wInd3x's no-data command. No public source repository or
revision for the cited Zig handler was located, and a direct origin fetch returned
HTTP 403. Treat its addresses and descriptions as research leads to check against
our exact binary, not a stable wire specification. Its reported accidental `94`
partition rewrite is further reason to exclude that command entirely.
[Chikuma update/restore research](https://chikuma.ringum.net/re/restore/)

Rockbox `ipodpatcher` requires a nonempty type-zero firmware partition followed
by a data partition. That assumed visible layout does not establish access to
the hidden Classic firmware area. `mks5lboot`, meanwhile, installs an alternate
NOR bootloader; its own prerequisites name Classic 1.1.2, 2.0.1, 2.0.4, and 2.0.5.
Neither is a stock RetailOS reinstall command.
[Partition predicate](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/utils/ipodpatcher/ipodpatcher.c#L253),
[mks5lboot scope](https://github.com/Rockbox/rockbox/blob/10ec9bd530c852631ce126795cacf20e7578017f/utils/mks5lboot/README)

## Native Classic 2.0.1 findings

These are static observations of family 33's original RetailOS, SHA-256
`220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
The existing Ghidra map was byte-checked against all three initialized regions.
Exports used `-readOnly -noanalysis`; the annotated project was not changed.
Names and C-like types remain analyst/decompiler interpretations. Addresses and
the corresponding assembly take precedence over inferred prototypes.

### Destination and capacity

The mass-storage object at `080dc190` sets its upload base to LBA `0x3f`.
`C6/91` at `080da5f4` uses that base plus its byte cursor divided by logical
sector size. It passes mode `1` to the backend; ordinary `WRITE(10)` passes `0`.
Backend `0812a8c0` selects different adapters for these cases. Constructor
`0812ab48` creates the ordinary adapter with remapping enabled and the upload
adapter with remapping disabled. `08251bbc` derives the ordinary adapter's
offset from the physical partition table, whereas the upload adapter retains
offset zero. `08251d84` and `08252aac` apply the selected adapter's offset.
This establishes a hidden physical firmware write path, rather than a write to
the FAT32 volume exposed by Windows.
[Adapter exports](../../../ipod-firmware-lab/artifacts/classic-update-backend4-20261117/),
[adapter initialization](../../../ipod-firmware-lab/artifacts/classic-update-backend8-20261117/08251bbc-FUN_08251bbc.c)

`08294bb0` returns a 4096-byte logical sector. `0812d670` puts the partition's
sector count multiplied by four into object field `+2e4`; `0812ddc8` emits this
field as `FWPartSize`. Independently, `C6/95` computes its size reply as sector
count times logical sector size divided by 1024. Neither `C6/95` nor any other
vendor command was sent to the physical iPod during this research.
[Capacity producer](../../../ipod-firmware-lab/artifacts/classic-update-backend9-20261117/0812d670-FUN_0812d670.c),
[XML publisher](../../../ipod-firmware-lab/artifacts/classic-update-backend11-20261117/0812ddc8-FUN_0812ddc8.c),
[size reply](../../../ipod-firmware-lab/artifacts/classic-update-backend9-20261117/080daf5c-FUN_080daf5c.c)

The chunk bounds check does **not** independently enforce the firmware partition's
end; it uses the ordinary backend's overall capacity. The Host must enforce the
reserved area's bound before starting. `C6/94` changes partition geometry and is
excluded. Normal raw Windows writes do not select this upload adapter.
[Chunk handler](../../../ipod-firmware-lab/artifacts/classic-update-storage-20261117/080da5f4-FUN_080da5f4.c),
[bounds](../../../ipod-firmware-lab/artifacts/classic-update-storage-20261117/080d8220-FUN_080d8220.c)

### Preservation and retries

`C6/90` resets the upload cursor, sets an update flag and attempts to save one
sector from the `hash` firmware image. `08043384` resolves the `hash` directory
entry; this is not a backup of the disk's partition table. `C6/92` restores the
saved sector through `FairPlay_WritePersistentRecordSlice` and frees its buffer.
A correct comparison must account for this preserved device-specific data.
[Start](../../../ipod-firmware-lab/artifacts/classic-update-storage-20261117/080d98e8-FUN_080d98e8.c),
[record read](../../../ipod-firmware-lab/artifacts/classic-update-storage-20261117/08043384-FairPlay_ReadPersistentRecordSlice.c),
[end](../../../ipod-firmware-lab/artifacts/classic-update-storage-20261117/080da308-FUN_080da308.c)

Three details prevent treating command acknowledgement as verified completion:

- Start still reports success if reading the preserved sector fails; it clears
  the saved pointer in that case.
- After an attempted chunk write, the cursor advances by the requested block
  count without checking that write's result again. Resending the same chunk
  can therefore target the next position.
- End ignores the record-write result. It frees the retained buffer without
  clearing the stored pointer, so repeating end is unsafe according to this
  static path. A timeout cannot be treated as permission to retry it.

These are source-derived failure cases, not failures deliberately triggered on
the connected iPod. A future executor must stop on ambiguous results, retain its
progress journal and distinguish recovery from retry. It must not automatically
reboot a partially uploaded image.

### Update reboot request

The standard `START STOP UNIT` path reaches `080d6fe4` and `080d9ecc`. With the
update flag at `+45c` set, it sets the reboot-pending flag at `+45d`. The USB loops
call `080d81f0`, which tests that flag, performs `080268dc`, calls `08350d20(0)`
and does not return to ordinary USB work. The latter reaches `082be31c`, including
the platform reset path. This establishes the native update reboot request; the
complete device-side update and stock boot were still untested at that research
checkpoint. The successful physical experiment is recorded below.
It also explains why a generic eject after a failed upload is not harmless.
[Reboot flag consumer](../../../ipod-firmware-lab/artifacts/classic-update-backend2-20261117/080d81f0-FUN_080d81f0.c),
[reset path](../../../ipod-firmware-lab/artifacts/classic-update-backend12-20261117/082be31c-FUN_082be31c.c)

### The apparent read-back command is not a backup route

RetailOS `READ BUFFER`, mode `18`, was followed through `080d8c84`, backend
vtable `0895d320 + 6c`, stub `0812a9a8`, and adapter `0825284c`. It creates a
one-MiB request with a fixed internal command byte `ff`; the reply would select
one 64-KiB slice. The selected controller is constructed at `081856d4`, with
vtable `0897c5b8`. Its command dispatcher `0825bc0c` sends command `ff` to error
completion with status `2`; the intervening `080ff054` only reads a request
field. This is not a qualified arbitrary-sector reader. No diagnostic command
was tried on hardware to discover its effects.
[USB handler](../../../ipod-firmware-lab/artifacts/classic-update-backend6-20261117/080d8c84-FUN_080d8c84.c),
[request construction](../../../ipod-firmware-lab/artifacts/classic-update-backend8-20261117/0825284c-FUN_0825284c.c),
[controller assembly](../../../ipod-firmware-lab/artifacts/classic-update-backend13-20261117/0825bc0c-FUN_0825bc0c.asm.txt)

### AUPD can do more than replace the disk image

The separately decrypted original AUPD has SHA-256
`dda3423b1ffecb5f638e8f66ccaecf67dd8c7ea33c01191130afb8b3fb036e41`.
The new bounded exporter imports it at `08000000`, verifies all input bytes,
exports 21 selected functions and discards the import. This avoids accidentally
interpreting its embedded disk-mode payload as the AUPD executable.
[Exporter](../../../ipod-firmware-lab/scripts/ghidra/ExportClassic33AupdUpdate.java),
[export provenance](../../../ipod-firmware-lab/artifacts/classic-aupd-update-20261117/provenance.txt)

Its main path `08007e34` processes the `flsh` item. For the one-MiB NOR descriptor
initialized by `080101cc`, the package's `0xf8000`-byte flash item takes the
repackaging branch: `08003b5c` handles embedded images and `08009d0c` wraps the
loader before the flash write. A raw comparison of that package item against
the stored NOR region is therefore not a test of the installed result.
[AUPD main](../../../ipod-firmware-lab/artifacts/classic-aupd-update-20261117/08007e34.c),
[NOR descriptor](../../../ipod-firmware-lab/artifacts/classic-aupd-update-20261117/080101cc.c)

The low-level write path `0800fed4` reads each erase block, compares the proposed
bytes with the stored bytes through `08007cd4`, and skips erase/program when
they match. This is byte equality, not a visible-version comparison. Therefore a
same-version reinstall is **not proven to avoid every NOR write**. The existing
one-MiB NOR backup remains recovery evidence, not proof of a future update's
postconditions.
[Write comparison](../../../ipod-firmware-lab/artifacts/classic-aupd-update-20261117/0800fed4.c),
[byte comparator](../../../ipod-firmware-lab/artifacts/classic-aupd-update-20261117/08007cd4.c)

## Implemented preparation and remaining hardware proof

`app/firmware/classic_update.py` now prepares the exact family-33 2.0.1 package
entirely offline. It requires matching package and complete-payload hashes,
manifest identity, normal-mode update observations, 4096-byte logical blocks and
sufficient reserved capacity including final-block padding. It describes only
`90`, `91` and `92`, with chunks no larger than eight blocks or the device's
smaller advertised maximum. The generator is not an installer and is not
connected to the Summary buttons.

The retained real IPSW passed preparation against the captured observations:

| Check | Result |
| --- | --- |
| Complete firmware payload | 93,515,776 bytes |
| Reserved capacity | 201,326,592 bytes (192 MiB) |
| Chunk size | 32,768 bytes |
| Data commands | 2,854 |
| Total described commands, including start/end | 2,856 |
| Padding required for this release | None |
| Reassembled stream SHA-256 | `42d6a0c18e7e3fc7cc181a15973ee12757769e25354d3320f0bff5c5d8ae17eb` |

The private, identity-bound preparation record is retained under
`.scratch/classic-stock-update-20261117/prepared-plan.json`. It records the capture
hash, package path, target identity and transcript edges. It records an offline
calculation, not a fresh connection token or execution approval.

## Physical read-only Disk Mode check

The user entered Apple's built-in Disk Mode with the button combination. A fresh
Storage capture confirmed the same product serial, family 33 and 2.0.1, with
`ForcedDiskMode=true`. Both captured SysInfo files matched their normal-mode
hashes. Windows continued to expose one FAT32 partition at byte offset 258,048.
[Disk Mode identity capture](../../../ipod-firmware-lab/captures/2026-11-17-classic-disk-mode-preflight/manifest.json)

Opening the physical disk with `GENERIC_READ` was denied by Windows with error 5.
The existing volume interface allowed a bounded SCSI check using only standard
`INQUIRY`, `READ CAPACITY(10)` and `READ(10)`. The opened handle's serial was
checked before the sector reads. Native SCSI reads returned 4096-byte sectors;
the exposed sector zero contains only one nonempty partition, type `0b`, starting
at LBA 63. LBA 63 contains a FAT32 boot sector rather than the firmware header.
Each sector was read twice and matched; the retained disk and volume identities
were rechecked afterward. The six-command successful transcript and sector
digests are retained. The earlier identity-only attempts encountered Apple's
NUL-padded/short serial response and did not issue sector reads.
[Read-only capture tool](../../../ipod-firmware-lab/scripts/capture_classic33_scsi_sectors.py),
[physical read results](../../../ipod-firmware-lab/captures/2026-11-17-classic-disk-mode-scsi-sectors/manifest.json)

This physically establishes that the hidden firmware area is not exposed by
ordinary sector reads in this Classic's forced Disk Mode either. It also
establishes that the current Windows environment can issue these standard SCSI
reads through a volume handle. It does not qualify vendor writes or require
changing the USB driver. The capture tool opens the handle with the access
required by Windows, but permits only the fixed data-in commands above. The
Windows structures and alignment follow Microsoft's pass-through contract.
[Microsoft SCSI pass-through](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddscsi/ni-ntddscsi-ioctl_scsi_pass_through_direct),
[request structure](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddscsi/ns-ntddscsi-_scsi_pass_through_direct)

After the user's ordinary restart, Windows briefly had not finished reconnecting
the volume; the initial capture attempt stopped before opening a session. Fresh
enumeration then identified the same Classic and a new capture confirmed
`ForcedDiskMode=false`, family 33 and 2.0.1 with no probe issues. Both SysInfo file
hashes still matched the original preflight. The normal-mode SCSI capture returned
the same capacity, MBR and FAT32 boot-sector hashes as Disk Mode. This closes the
read-only mode-comparison experiment; it is not an installation test or a hash
verification of every media file.
[Normal-mode return](../../../ipod-firmware-lab/captures/2026-11-17-classic-normal-return/manifest.json),
[normal-mode sector capture](../../../ipod-firmware-lab/captures/2026-11-17-classic-normal-scsi-sectors/manifest.json)

## Qualification requirements after the initial mode comparison

The next hardware milestone then required an independently verified way to retain
and read back the existing firmware area, especially its preserved `hash` sector.
The public update writer does not supply this. At that checkpoint, a bounded
acquisition helper or captured original-updater transaction was a research route,
not an already qualified fallback. The Windows transport lives in Storage and holds an
exclusive operation bound to the observed physical device and Connection
Generation. It stops on short transfers, failed SCSI status or disconnects. Its
physical qualification then covered standard reads only, as recorded below. A
persisted progress journal and tested failure handling were required before the
first upload; physical interruption recovery remains a separate unqualified path.

Before a persistent test, retain recovery material and record the data volume's
baseline. Afterward verify reconnection, firmware identity, normal boot and
unchanged media/library evidence. Account for Apple's preserved record and any
device-side update bookkeeping when verifying firmware bytes. A matching version
string alone cannot prove a same-version reinstallation. No firmware update,
formatting, partition change or bootloader installation was performed in this
initial mode-comparison investigation. The user performed ordinary button restarts to enter Disk Mode
and return to normal mode; that return was physically observed through fresh
USB identity evidence. The tools sent no reset or eject command.

Nano 3–5 can potentially share the command codec and transfer framing. Their
mode transitions, package and bootloader policies still need individual profiles;
Nano 6/7 have additional preparation in upstream. Classic families 24, 35 and 38
likewise must not inherit family 33's native handler qualification automatically.

RepriseOS components declare GPL-3.0-only; wInd3x carries a GPLv2 license, while
its SCSI serializer credits Apache-2.0-derived definitions. Rockbox files carry
their own GPL headers. Preserve provenance and check each copied file's terms;
the protocol facts can guide a small independent implementation without importing
an entire installer. No source code was copied into production by this research.
[Reprise license](https://github.com/lgreitis/repriseos-installer/blob/96536d38d089ef3a198fe1cedd8522c6ce646153/src-tauri/Cargo.toml),
[wInd3x license](https://github.com/freemyipod/wInd3x/blob/fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60/COPYING),
[serializer attribution](https://github.com/freemyipod/wInd3x/blob/fbd9f652b7edf31cbeac3dfb9afa8fc7d20c6f60/pkg/usbms/scsi.go)

## Exclusive Storage transport qualification

The production Storage boundary now provides typed SCSI commands and an exclusive
SCSI Session. Its Windows implementation uses the retained Volume GUID, checks
the native disk number and exact standard INQUIRY identity before and after
locking, honors adapter transfer/alignment limits, and closes on failure without
retrying or sending a finalizer/eject. The session holds the same Host writer
lease as filesystem mutations. Existing device sessions must close first;
competing session/probe/eject requests fail while exclusive access is reserved.
See [ADR-0276](../adr/0276-own-exclusive-scsi-sessions-in-storage.md).

At `2026-11-17T09:21:21Z`, the bounded capture tool successfully used this transport
on serial `8P840FN62C7`, disk 2. Native identity checks succeeded and Windows
granted the exclusive volume lock. The experiment issued READ CAPACITY(10), then
READ(10) for LBA 0 and 63 twice each. The sectors matched the earlier normal-mode
and Disk Mode hashes. After closing the native handle, ordinary filesystem access
worked again and both SysInfo files retained their baseline hashes. The disk,
serial, capacity, Volume GUID, and mount identity remained unchanged. No vendor
command, data-out, reset or eject was issued. Windows volume locking itself
flushes any pending filesystem cache; this was not a firmware installation.
[Capture tool](../../../ipod-firmware-lab/scripts/capture_classic33_storage_scsi.py),
[capture results](../../../ipod-firmware-lab/captures/2026-11-17-classic-storage-scsi-session/manifest.json),
[Windows volume locking](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_lock_volume)

Tests exercise simulated disconnects, generation changes during open, lock denial,
competing sessions, native identity mismatch, adapter alignment and transfer
limits, incomplete responses, SCSI sense retention, and absence of retries or
cleanup commands. This verifies the host transport contract; it does not establish
that a physical vendor upload succeeds or preserves the hidden persistent record.

Further static inspection ruled out two shortcuts. The READ(10) bounds handler
checks addition overflow as well as start/end bounds, so negative or wrapped LBAs
do not provide an obvious hidden-area read. The family-33 2.0.1 BuildID and
VisibleBuildID producer calls `08143488` with compiled constants `(9, 1, 0x80, 0)`
and `(2, 1, 0x80, 0)` respectively. Editing the firmware directory's version field
alone would not provide a changed version marker after boot. This is static
evidence against the exact OSOS digest already recorded above; no version patch
was uploaded.
[Additional native export](../../../ipod-firmware-lab/artifacts/classic-update-backend14-20261117/)

At that stage, the next acquisition candidate was a temporary RAM helper based on the pinned
`osos-lab` commit `d2c8e357d58591bdaa70bb6be9da191f489554a6`. Its existing
`usb-helper/main.c` calls the Rockbox ATA driver directly and captures physical
layout sectors, but `usb-helper/usb.c` exposes a file-upload protocol and only
bounded layout diagnostics, not an arbitrary raw-sector download. The build also
requires the separate pinned Rockbox tree and ARM GCC 9.5.0. Those facts do not
qualify it as a firmware-backup tool. A dedicated acquisition variant must reject
all ATA writes, avoid filesystem mounting/writing, expose bounded sector reads,
retain disk identity and sector geometry, and verify repeated reads before its
captures can be used as recovery material. No helper was built or booted during
that transport increment; the connected iPod was left in stock normal mode.
[Pinned helper source](https://github.com/lgreitis/osos-lab/blob/d2c8e357d58591bdaa70bb6be9da191f489554a6/usb-helper/main.c)

## Physically verified recovery material and upload preparation

The subsequent acquisition increment built and physically exercised a dedicated
read-only variant of the existing 89,440-byte fixture, preserving its hardware
initialization and return path. The replacement main tail performs two bounded
ATA reads, compares them, and computes CRC32 and SHA-256. Both the upload permission
function and ATA sector-write entry point reject writes. No filesystem mounting,
file upload, or NOR write path is entered.

The exact helper SHA-256 is
`8261b0e400addff0217d2c5a278f2b4e829bb64f6d7c6b221b42828526bfacc8`.
Its base fixture is
`07af9b210c620c482e80fbeadf8cd02db15ec998beff8cd98fe8acf11228af13`.
The added stub uses ARM GCC 13.3; original helper code outside the recorded patches
remains unchanged. Fifteen emulator cases check geometry, ranges, read failures,
disagreement, digests, retained data and write guards. The fixture SHA functions
also passed 28 separate known-answer comparisons.
[Builder](../../../ipod-firmware-lab/scripts/build_classic_acquisition.py),
[stub](../../../ipod-firmware-lab/scripts/classic_acquisition/read_stub.c),
[emulator checks](../../../ipod-firmware-lab/scripts/test_classic_acquisition.py),
[retained Host patch](../../../ipod-firmware-lab/scripts/classic_acquisition/host.patch)

An initial external-DRAM read after return stalled DFU and required the user to
restart into DFU. The BootROM cold-init path disables the SDRAM clock/refresh;
retention of external DRAM was not established. The qualified variant returns only
a 4096-byte prefix and full-range digest through retained **internal RAM**. It
does not apply the proposed cold-init clock patches. The Host tolerates a transient
USB enumeration disappearance while finding the returned nonce-bound session;
it does not retry device writes or relaunch an ambiguous helper.

Physical reads established these units and bounds:

| Item | Observed value |
| --- | --- |
| Raw ATA logical sector | 512 bytes |
| Raw ATA total sectors | 245,452,800 |
| Raw MBR partition units | 4096 bytes |
| Firmware partition | Type `3f`, start 63, count 49,152 |
| Firmware raw byte offset | 258,048 (ATA LBA 504) |
| Firmware partition capacity | 201,326,592 bytes (192 MiB) |
| Raw data partition | Type `0c`, start 49,278, count 30,632,321 |
| Proposed firmware write span | 93,515,776 bytes |

The on-device directory is at firmware-relative byte 20,480. The header's 16,384
directory offset has a 4096-byte bias; it must not be used as an absolute byte
offset. The persistent `hash` entry is at relative byte 93,507,584 and spans 4096
bytes. Captured raw MBR, header, directory and persistent record all agreed across
two device reads and Host CRC/SHA checks.

The original Apple payload plus those captured sectors reconstructs the complete
proposed overwrite span. Twenty-three independent device-side, double-read
SHA-256 comparisons cover every byte of that reconstruction, in chunks of at most
4 MiB. All matched. Its SHA-256 is
`a0ff19a5f1eed0d883caf980d06e8c81e931ce623f8765a99ed19b5616715ab7`.
The captured persistent sector already matches the package's corresponding bytes;
the only current package differences are five directory bytes. These include
AUPD bookkeeping, so a post-boot comparison must inspect the actual directory.
This is a recoverable preimage of the **entire write span**, not a whole-disk or
complete 192 MiB partition backup.
[Reconstruction and verification](../../../ipod-firmware-lab/scripts/verify_classic_preimage.py)

A fresh 1 MiB NOR dump completed with a shifted second pass and independent edge
checks in 157 seconds. Its digest is
`bb34f00db4e81f2b5a5b367523c06f46f0fa91078ca9fb72fdfe9b38ebe1aa42`,
identical to the October 26 dump of this device. Recovery files, range receipts,
helper provenance and the fresh NOR evidence are retained under
`%LOCALAPPDATA%/iOpenPod/firmware/recovery/8P840FN62C7/2026-11-17-preflash/`.

The new `classic_upload` executor enforces the pinned original package, complete
recovery range coverage, raw partition bounds, and live visible capacity/layout.
It uses Storage's exact-identity exclusive SCSI Session. An atomic Host journal
records intent before each command and acknowledgement afterwards. Any transport,
short-transfer, callback or journal failure stops further commands without retry,
finalization or eject. A completed stream remains
`awaiting-independent-verification`; it is not an installation receipt. Thirteen
workflow tests exercise those failure and recovery-validation boundaries, alongside
the existing transport and offline-plan tests.

The lab driver separates read-only preparation, upload, reboot request, and
normal-mode comparison. It rechecks live VPD and retains library database and
identity-file baselines before upload. It is restricted to this selected serial
and remains outside the UI. This preparation checkpoint preceded the physical
reinstall described below.
[Research driver](../../../ipod-firmware-lab/scripts/classic_stock_experiment.py)

## First physical stock reinstall

The selected Classic was returned from DFU to normal mode. Initially Windows saw
no Apple USB device, so the read-only preflight stopped without a firmware write.
After the user reconnected the cable, fresh USB, SCSI and VPD observations matched
serial `8P840FN62C7`, USB PID `1261`, updater family 33, firmware 2.0.1 and the
retained Volume identity. Library databases and identity files were copied to
persistent Host recovery storage before opening the exclusive upload session.

At `2026-11-17T10:06:03Z`, the preflight was complete. By `10:06:20Z`, all **2856
commands** had succeeded: one `C6/90`, 2854 `C6/91` chunks totaling **93,515,776
bytes**, and one `C6/92`. The image was the original pinned Apple payload, with no
marker or firmware modification. There was no transport error, short transfer,
retry, restore finalizer or repartition command. The journal retained exact
acknowledged byte/command counts and no pending command.

The separately requested `START STOP UNIT` CDB `1b0000000200` was acknowledged at
`10:06:28Z`. USB disconnected during reboot, then the same Classic returned in
normal mode. At `10:07:41Z`, fresh VPD still reported **2.0.1**, with neither
ForcedDiskMode nor CorruptDataPartition set. The following files matched their
pre-upload copies byte for byte:

| File | Bytes |
| --- | ---: |
| `iPod_Control/Device/SysInfo` | 235 |
| `iPod_Control/Device/SysInfoExtended` | 3025 |
| `iPod_Control/iTunes/iTunesDB` | 3,496,267 |
| `iPod_Control/Artwork/ArtworkDB` | 314,172 |
| `Photos/Photo Database` | 13,500 |

The absent iTunesCDB/iTunesSD files remained absent. A fresh exclusive standard-read
capture confirmed the same capacity, visible MBR and FAT boot sector. This verifies
the retained database and layout postconditions; it is not a hash comparison of
every media file on the data volume.

The user then re-entered DFU for independent post-upload reads. The raw MBR matched
its baseline. All 23 newly acquired double-read SHA-256 ranges matched the retained
preimage, covering **every byte of the 93,515,776-byte write span**, including the
device's persistent record. This verification uses fresh nonce-bound helper
launches and does not rely on the upload transport's success statuses.

The subsequent 1 MiB NOR dump passed both shifted read passes and edge checks in
158 seconds. It matched the complete pre-update NOR byte for byte, with digest
`bb34f00db4e81f2b5a5b367523c06f46f0fa91078ca9fb72fdfe9b38ebe1aa42`.
Thus this particular same-version reinstall left NOR content unchanged; that
observation does not establish that all update packages avoid NOR writes.

The installed span's digest is again
`a0ff19a5f1eed0d883caf980d06e8c81e931ce623f8765a99ed19b5616715ab7`.
It differs from the uploaded package digest only by the previously observed five
directory bookkeeping bytes: AUPD flags/length and the later directory word. The
same-version reinstall naturally leaves the displayed version at 2.0.1. No version
marker was necessary. The verified result establishes the successful stock update
path on this device; it does not exercise interruption recovery or establish
support for another Classic or Nano family.

The upload journal, before/after filesystem comparisons, visible and raw layout
captures, and complete range receipts remain together in the persistent recovery
directory named above. The offline evidence verifier checks their identities,
coverage, digests and acquisition ordering before publishing an installation
verification report; it never accesses the device.
[Evidence verifier](../../../ipod-firmware-lab/scripts/verify_classic_installation.py)

Finally, the user returned the iPod to normal mode and reconnected USB. Fresh
SCSI/VPD and SysInfo captures again identified the same healthy family-33 2.0.1
device. At `2026-11-17T10:19:58Z`, the offline verifier published
`installation-verification.json` and advanced the upload journal to
`verified-stock-reinstall`. Its five evidence tests include rejection of an
incomplete upload, changed library, missing final firmware range, and missing NOR
cross-check. The iPod was left connected in normal mode. Device Summary remains
download-only; no installation action was added to the GUI in this experiment.
