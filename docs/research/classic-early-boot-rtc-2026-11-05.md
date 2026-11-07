# Classic 24/33 early boot and the running RTC

Research date: **2026-11-05, America/Detroit**. This investigation follows the
remaining non-OSOS clock-initialization seams in the latest family 24/1.1.2 and
33/2.0.1 inputs. It extends the [raw-clock follow-up][previous]. The analysis and
native probes are offline. Family 33 uses previously acquired plaintext; family
24 uses the newly authorized, separately operated device-assisted decryption
described in the [acquisition report][new-acquisition]. That acquisition performed
no persistent firmware installation. These stages are distinct evidence.

## Findings

The qualified **24/1.1.2 and 33/2.0.1** loaders contain directly reachable early
PMU initialization sequences. Bounded native Thumb probes reproduce 21 writes,
including **one zero byte to register `0x58`**. None of these writes addresses
the calendar/alarm/retained-metadata range `0x59..0x6e`. The significance of
`0x58` on the exact Apple PMU remains unresolved. Consequently, this is not
proof that early boot leaves the running RTC unchanged. [Entry and initializer][pre-entry],
[native traces][vectors]

The later EFI PMU driver publishes its generic register interface under an
identified GUID. Of the 41 extracted modules in each loader, the only other exact GUID
occurrence is in `Ata`; its traced use writes two bytes to register `0x1a`.
This resolves an actual indirect-interface consumer beyond the earlier generic
driver inspection. It does not reveal a civil-calendar seed or a UTC convention.
[Protocol registration][vectors], [Ata consumer][ata]

Family 24 has two different initialization payload bytes, independently observed
in native execution. Its checksum-qualified embedded Disk Mode image also has
the same bounded raw-clock/software-correction distinction as family 33. The
inspected date-setting paths do not establish the raw clock's original UTC or
local-time convention. [Family 24 vectors][vectors24], [disk evidence][disk24]

## Qualified inputs and maps

The [verifier][verifier] reopens both complete IPSWs, checks their hashes,
extracts the named firmware member, verifies its hash, and validates the AUPD
directory entry and IMG1 header. The completed receipt retains the exact
offsets, logical/encrypted lengths, and hashes.

| Latest target | IPSW SHA-256 | AUPD IMG1 SHA-256 |
| --- | --- | --- |
| 24 / 1.1.2 | `e753abfb11aaeaa6fd1d7257e87f4e53b6b5d923b1de0e4c9c63c30e0dac9d1a` | `8a975cadbeb93d89a919e4a8d10a38b282149791a2ce2986aec40b5527b35878` |
| 33 / 2.0.1 | `17b16ceb4e906cf5636e7389292c40149c503a6fe3df749b3c8447290aa181d5` | `eadb48e45ceadda2e663546339cd4629cb3cab3a92270d514d41481d0ea93327` |

Both AUPD images use encrypted IMG1 format 3. The 33 plaintext AUPD was obtained
in the earlier, recorded device-assisted acquisition; this pass does not repeat
decryption. Its SHA-256 is
`dda3423b1ffecb5f638e8f66ccaecf67dd8c7ea33c01191130afb8b3fb036e41`.
The verifier checks that its slice at byte 148552, length 129024, exactly equals
the preserved loader with SHA-256
`8d028296d20d7162eb109d062239ba510fe842510e006178040caacbabead1b8`.
That complete loader also matches the historical pinned profile. This is a
provenance chain plus independent loader fingerprint, not a newly repeated
cryptographic proof of the whole plaintext AUPD. [Preparation manifest][preparation],
[acquisition record][acquisition], [verification][receipt]

The earlier family 33 offline extraction produced 41 EFI executable modules. All are
hashed again. The four modules inspected here have these exact identities:

| Module | Bytes | SHA-256 |
| --- | --- | --- |
| PreEfi | 10048 | `af4c378fc2e244804b02d8eaf404bbe1f0260924e8b8c7fd1fa9db85347ef1e5` |
| DxePcf50635 | 4288 | `e461487380c597e15e2dbe49be81dd27f4850e39d16515d0cd71cfce0eb07899` |
| Ata | 12128 | `8e6bcda99b53f7f10547da5a6833781fa65113a564783ef75ff9b2dd324492cc` |
| DxeSmbus | 1952 | `1a20bfe1a9d287e5b8d5f887f5d1fc08e422b7454ef5a9d1cd7ad8d6d4c1a26d` |

Addresses in the following family 33 EFI sections are **PE module-relative RVAs**,
not OSOS addresses or measured
live load addresses. Inspected section RVAs equal file offsets. PreEfi's PE
preferred ImageBase is `0x2200e1f4`, with entry RVA `0x2351`; the other three
preferred bases are zero. The receipt records PE sections, sizes, and entry
points. Native probes isolate specific Thumb functions at their RVAs and stub
hardware/EFI calls; they do not emulate the full loader or its relocation.
[PE maps and span hashes][receipt]

## PreEfi directly calls the early PMU initializer

PreEfi entry `0x2350` calls controller/memory setup helpers, then at `0x236e`
calls function `0x070e` with a pointer to a boot-state output word. It checks
the returned status and passes the output word into later setup at `0x237c`.
This establishes reachability from the module's actual PE entry, rather than
merely locating an unused register-writing routine. The subsequent complete
boot handoff and every caller of later setup are outside this bounded probe.
[Entry ARM/Thumb span][pre-entry]

Initializer `0x070e` calls local hardware setup `0x065e`, reads register `0x16`
and tests bit 2, then reads `0x0c` and tests bit 3. It clears `0x0c` through a
one-byte write. When neither tested bit is set, it writes `0x11` to the supplied
output word; otherwise that word retains zero. These are observed bit tests and
output values, not asserted hardware reset-cause names. [Initializer][pre-init]

The PMU write helper `0x06c0` rejects data counts above eight, prepends the
register address, and calls the I2C helper `0x05ce` using endpoint `0x73`.
The corresponding read helper `0x06f0` selects a register and performs a read
through the same endpoint. These lower routines establish that the initializer's
arguments are PMU register addresses and data lengths. [Read/write helpers][pre-io]

All four combinations of the two tested bits produce the following identical
write sequence under successful synthetic transport responses:

```text
0c:00        2d:1501      37:1504      2f:1501      3b:008c
13:030000    17:00        22:2f010010  26:0901      1a:1800
1d:0a        33:0901      39:1800      18:0a        19:04
58:00        07:b000fefcff            86:fd        0d:dfaa480527
17:01        29:000506
```

Each entry is `start_register:consecutive_bytes`. The vector assertions check
the full range of multibyte writes, not just their start addresses. None
overlaps `0x59..0x6e`. The native code also performs four PMU reads; the later
reads of `0x02` and `0x85` use synthetic zero bytes in these tests.
[Exact traces and instruction counts][vectors]

The `0x58` write is anchored by `MOVS r0,#0x58` at `0x08a2`, zero-byte staging
at `0x08a6`, and `BL 0x06c0` at `0x08a8`. The inspected routine does not then
write a year/month/day/time sequence. The retained Rockbox shared PCF5063x
header leaves `0x58` unnamed immediately before the running-calendar registers;
this is not an exact PCF50635 specification. Neither that header nor the
related PCF50633 manual establishes the side effects of Apple's write to this
register. Do not call it a clock reset, oscillator enable, or harmless reserved
write without further evidence. [Initializer bytes][pre-init],
[retained shared register definitions][registers]

Rockbox's independently maintained iPod6g PMU initialization also contains
`0x58, 0x0`, with a comment labeling it reserved. This corroborates the write
pattern, not a hardware function or reset guarantee; it is software evidence,
not a manufacturer specification. [Pinned Rockbox initialization][rockbox-init]

The probes inject a failed transport status at each of the 25 I/O positions as
well. Every case returns the failure after the corresponding prefix; no such
path introduces a calendar or metadata write. Hardware setup, successful read
contents, error values, and service completion are synthetic. Thirty native
cases in total comprise 29 initializer cases and one protocol-install case;
they are not observations of a physical iPod. [Vectors][vectors]

## The generic EFI register interface has a traced consumer

DxePcf50635 entry `0x05de`, continued at `0x0668`, locates three protocols and
installs seven interfaces. A bounded native run with synthetic EFI services
records the actual variable argument list. The generic PMU interface is:

```text
GUID       3d4aa229-b4e3-4fd9-9ec9-90ea8123833e
interface  RVA 0x0f1c
read       stored Thumb pointer 0x0221 → code RVA 0x0220
write      stored Thumb pointer 0x024d → code RVA 0x024c
```

The driver locates SMBus GUID `e49d33ed-513d-4634-b698-6f55aa751c1b` and uses
that interface for generic register transfers. Exact GUID-byte searches across
all 41 extracted modules find the SMBus GUID only in DxeSmbus and DxePcf50635,
and the generic PMU GUID only in DxePcf50635 and Ata. This is a bounded exact
identifier search, not a guarantee that interfaces cannot be passed between
objects or identifiers constructed indirectly. [Native registration][vectors],
[GUID occurrences and pointer guards][receipt]

Ata entry `0x02e6` locates the generic interface at `0x034a..0x034e`, retaining
the returned pointer at stack `+0x20`. It stages bytes `6b 01`, loads interface
slot `+4`, and calls it at `0x0364` with register `0x1a` and length two. The
pointer is local to this use in the inspected entry; this is not a write of
metadata at register `0x6b`. Here `0x6b` is a **data byte**, a distinction that
an immediate-value search alone would miss. [Ata disassembly][ata]

The driver's other published methods and their generic I/O calls are retained
as a disassembly span. No directly identified calendar-seed operation emerges
from these inspected methods. The exact `rtcV` signature word used by the OSOS
retained-metadata path, little-endian bytes `56 63 74 72`, has no exact occurrence
in the 41 extracted modules. That search does not exclude a constructed
signature, earlier BootROM action, separately loaded code, or the unknown
side effects of register `0x58`. [Method span][methods], [signature scan][receipt]

## The updater and embedded disk-mode executable are separate evidence

The independent [AUPD verifier][aupd-verifier] derives the updater's executable
map from startup literals: code `0x08000000..0x080124ec`, initialized bytes
through `0x0802441c`, and BSS through `0x080584c8`. The large following payload
is a separately relocated flash container; its strings are not automatically
updater runtime references. Seven `flsh` directory entries and their additive
checksums independently delimit seven embedded images. [AUPD receipt][aupd]

The updater's generic PMU write routine `0x0800f868` has seven identified direct
branch callers in its executable region:

| Caller | Start register | Data length |
| --- | --- | --- |
| `0800f5e4` | `1a` | 1 |
| `0800f690` | `29` | 1 |
| `0800f700` | `52` | 1 |
| `0800f718` | `53` | 2 |
| `0800f858` | `28` | 1; conditional tail branch |
| `0800f8c0` | `1d` | 1 |
| `0800f8e4` | `1b` | 1 |

Its lower I2C write `0x0800d700` has two identified direct callers: register
selection for the PMU read at `0x0800f7f4`, and the PMU write at `0x0800f89c`.
The I2C read `0x0800d508` has caller `0x0800f80c`. Exact aligned pointer searches
find no reference to those four PMU/I2C functions in initialized updater bytes.
These checked paths do not write `0x59..0x6e`. Computed pointers, alternative
peripheral access and embedded executables remain outside that negative claim.
The updater artifact has 32 guards and 26 listings. [AUPD receipt][aupd]

The embedded **disk-mode** image is a meaningful additional seam, not a string
search false positive. Its exact AUPD offset is `0x0e7978`, size `0x348c4`,
SHA-256 `6bf00b7ad65b08983f39f598a7a82bd2d009fe9f0d80abadddc3ed92f04a68d4`.
Its footer checksum is `0x013d23f1`. This image contains both the `rtcV`
metadata signature and the `RTC_TIME_ADJUST`/`RTC_ALARM_ADJUST` strings.
The strings alone do not identify a clock initializer. [Container extraction][aupd],
[disk verifier][disk-verifier]

### Independent disk-mode relocation map

The footer's `0x08000000` load address describes the initial placement, not the
final address of every byte. Startup entry file `0x06ec` enters relocation code.
The checked copy literals and a native execution of the actual overlapping copy
routine establish this map:

| Image source | Runtime destination | Extent |
| --- | --- | --- |
| `0x0000` | `0x22000000` IRAM | `0x730` bytes |
| `0x0730` | `0x08000000` DRAM | `0x34190` bytes |
| No source; zeroed | `0x08034190` BSS | `0x10acc` bytes, ending `0x08044c5c` |

Four trailing image bytes are outside the two initialized copy spans. The
native relocation fixture stops at the first branch into relocated IRAM and
checks both destination spans byte-for-byte; it does not run hardware setup.
Consequently, the later DRAM address is `0x08000000 + file_offset - 0x730`.
Simply adding a file offset to the initial load address mislabels the date paths.
[Map guards and native fixture][disk], [startup copy][disk-startup]

### Disk-mode clock paths preserve the same raw/correction distinction

| Role | Relocated runtime address |
| --- | --- |
| Calendar subsystem initialization | `08007cdc` |
| Retained metadata restoration | `0800d694` |
| Signature/offset/DST reader | `0800acc4` |
| Twelve-byte calendar receive | `08011474` |
| Decoded calendar setter | `08008a1c` |
| Adjusted calendar setter | `08008e94` |
| Raw calendar read wrapper | `0802817c` |
| Raw calendar write wrapper | `080283b8` |
| PMU calendar-bank writer | `0802c8c0` |

Subsystem initialization directly calls metadata restoration at `0x08007cf8`.
The restoration copies retained offset/DST into the shared RAM record when its
getter succeeds. On failure it initializes that record to year 2000, day-index
3, January 4, midnight, and zero offset/DST. The native fixtures reproduce both
paths with the metadata getter stubbed and reject any attempted calendar/PMU
write. That fallback is not a raw RTC seed. [Initialization and restoration][disk],
[restoration ARM][disk-restore], [native vectors][disk-vectors]

The date setter still passes selector zero to the adjusted setter, which reads
raw bank zero and computes software correction. The initialized correction
words at `0x080324c0` are zero in this image; later execution can change them.
The native arithmetic fixtures use a synthetic raw calendar at 18:16:05 and
request 19:16:05 or 17:16:05 on the same date. The resulting normalized
corrections are `(0 days, 3600 seconds)` and `(-1 day, 82800 seconds)`, with
only a bank-zero read recorded. Neither case writes the running calendar.
[Adjusted setter][disk-adjusted], [native vectors][disk-vectors]

The adjusted setter's selector-one branch calls the raw write wrapper at
`0x08008f28` with selector one. A separate native fixture records that selector
at a stubbed raw-write entry; the alarm-bank mapping is static instruction
evidence, not an executed bank writer or hardware write. The aligned ARM branch scan finds this sole direct caller
of the wrapper, and the wrapper's call at `0x080283d4` is the sole direct call
to the bank writer. Neither function has an aligned exact pointer reference in
the two initialized runtime regions. The generic PMU transport has 18 direct
branch hits, including computed register paths; this is not closure of every
possible writer. [Disk search receipt][disk]

The twelve-byte receiver invokes decoder `0x0800dd28`, then calendar setter
`0x08008a1c`. Metadata persistence separately writes the signature plus offset
and DST through the general-purpose register window beginning at `0x67`;
these are different from raw calendar register writes. These concrete disk-mode
paths still do not establish the raw clock's original timezone convention.
[Receive and metadata disassemblies][disk]

The disk artifact has **six bounded native cases, 29 exact word/call guards,
and 19 disassembly spans**. Hardware, clock-counter and synchronization/copy
boundaries are stubbed in the isolated date tests. The actual startup copy is
executed, but no full boot or physical device behavior is simulated.
[Disk verifier receipt][disk]

## Independently qualified family 24 boot paths

The family 24 firmware member is `Firmware-24.9.1.2`, SHA-256
`e010f54a8460bf2726bccf07bfd406281257d8e572d0a8d1193e8f03b1649752`.
Its AUPD component begins at byte 91750400. The IMG1 payload reports 1164356
logical bytes, padded to 1164368 encrypted bytes. The separately authorized
acquisition produced 1164368 plaintext bytes with SHA-256
`98f66b2a8af0bb8a6c27cc27630ff4b54d159fa485dae0fa0a67dfbf112942e4`.
No independent whole-plaintext reference hash was supplied to that decryption;
the report's `reference_matched=false` therefore means no reference was given.
The subsequent byte qualification is independent of that flag.
[Acquisition][new-acquisition], [input receipt][receipt]

The verifier checks the `Plyd` record at `0x243fc`, the `FwUp` record at
`0x2440c`, and seven embedded `flsh` entries beginning at `0x11c228`.
Every embedded image's additive checksum passes. The loader starts at
`0x24428`, has 129024 bytes, and SHA-256
`460368ec325ab567b3ea1d0c5e2eb09df7dac0502c1141257ffb32d661248f96`.
Its firmware-volume header and volume size are checked before the separately
preserved loader and extracted modules are compared. The pinned offline
`reprise firmware extract-efi` extraction yielded 41 modules. This is actual
family 24 plaintext evidence, not substitution of family 33 annotations.
[Container and module qualification][receipt]

| Family 24 module | Bytes | SHA-256 |
| --- | --- | --- |
| PreEfi | 10048 | `f53c1af9b4bb1a3d7eed89f50d624b2cc9f91eead9c5778b658f91247398af27` |
| DxePcf50635 | 4288 | `01726409a0cd017551e8951ddf04dd517d843cb54c10227d770393a2a47c47d8` |
| Ata | 12128 | `5ea9bc8248e458b3ecc3a0edd4ec140245e338c7cb5d232e72078ee207e5ba4c` |
| DxeSmbus | 1984 | `2744c4d000d485c8e38cce31c445022270b9a15fd4fe6f4babb5da1641b93035` |

Family 24 PreEfi has preferred base `0x2200e244` and entry RVA `0x233d`.
Its actual Thumb entry at `0x233c` calls PMU initializer `0x06fa` at `0x235a`;
the hardware/read/write helpers are `0x064a`, `0x06dc`, and `0x06ac`.
The zero write to register `0x58` is guarded at instruction `0x088e`, staging
`0x0892`, and call `0x0894`. The same four input-bit combinations and 25
transport failure positions are executed independently using family 24 bytes.
[Family 24 entry][pre24-entry], [initializer][pre24-init], [native cases][vectors24]

The native trace has the same ordered register starts and data lengths as 33,
but these two payloads differ:

| Register start | Family 24 | Family 33 |
| --- | --- | --- |
| `07` | `b0 03 fe fc ff` | `b0 00 fe fc ff` |
| `0d` | `df aa 4a 05 27` | `df aa 48 05 27` |

Neither differing byte is assigned an unproven hardware meaning here. The
`0x58` observation and its unresolved side effects apply independently to both
images. The family 24 protocol-install probe also passes. Selected runtime
code/data spans of DxePcf50635 (`0x220..0xfe0`), Ata (`0x220..0x2ab8`), and
DxeSmbus (`0x220..0x6e8`) match family 33 byte-for-byte; full module hashes differ.
Their PE section maps are checked separately. Both GUID searches are repeated
across all 41 family 24 modules, with the same exact occurrence sets and no
literal `Vctr` signature. [Maps, equality guards, and scans][receipt]

### Family 24 updater executable

Startup literals independently delimit code through `0x080124cc`, initialized
bytes through `0x080243fc`, and BSS through `0x080584a8`. The PMU writer is
`0x0800f848`; its seven direct callers and their immediate register/length
arguments are guarded:

| Caller | Start register | Length |
| --- | --- | --- |
| `0800f5c4` | `1a` | 1 |
| `0800f670` | `29` | 1 |
| `0800f6e0` | `52` | 1 |
| `0800f6f8` | `53` | 2 |
| `0800f838` | `28` | 1; conditional tail branch |
| `0800f8a0` | `1d` | 1 |
| `0800f8c4` | `1b` | 1 |

The PMU reader is `0x0800f7b4`. Lower I2C writer `0x0800d6f4` has direct
callers `0x0800f7d4` and `0x0800f87c`; reader `0x0800d510` has direct caller
`0x0800f7ec`. Endpoint `0x73` is guarded in the PMU transfers. No exact aligned
pointer to these four functions occurs in initialized updater bytes. The
identified write spans exclude `0x59..0x6e`; computed pointers or other
peripheral access remain outside this bounded claim. [Updater scans][receipt],
[PMU disassembly][aupd24-pmu]

### Family 24 Disk Mode

The independent [family 24 disk verifier][disk24-verifier] reads the checksum-
qualified image at AUPD `0xe7d08`, size `0x34514`, SHA-256
`669b9e32f4c284cd6a5572a5987901d45b3bea91f397a91aa5faa0ac045dc0b6`.
Its additive checksum is `0x013b7b0f`. Native startup copying establishes IRAM
`0x22000000..0x22000730` from image offset zero and DRAM
`0x08000000..0x08033de0` from image offset `0x730`; BSS has `0x10e7c` bytes,
ending at `0x08044c5c`. These extents differ from 33 and are not assumed from it.
[Family 24 map and fixtures][disk24]

| Role | Family 24 runtime address |
| --- | --- |
| Calendar initialization / metadata restoration | `08007cb8` / `0800d4fc` |
| Signature/offset/DST reader | `0800ac10` |
| Twelve-byte receiver / decoder | `08011364` / `0800dbd0` |
| Calendar setter / adjusted setter | `08008994` / `08008dec` |
| Raw read / raw write wrapper | `08027e54` / `08028090` |
| PMU calendar-bank writer | `0802c550` |

The same six native cases run independently: startup relocation; plus/minus one
hour through raw-bank-zero reads, yielding software corrections `(0, 3600)` and
`(-1, 82800)` at `0x0803211c`; alarm-selector dispatch to a stubbed raw writer;
and valid/invalid retained
metadata restoration. The invalid path initializes shared RAM at `0x08034e20`
to 2000-01-04 midnight with zero offset/DST. It does not seed the raw RTC.
The sole aligned direct caller of the raw-write wrapper is `0x08008e80`,
preceded by selector one at `0x08008e7c`; the wrapper alone directly calls the
bank writer at `0x080280ac`. No exact aligned pointer to either occurs in the
two initialized regions. As for 33, this does not close computed register
writes or the complete transport dispatch. This artifact has six native cases,
29 word/call guards, and 19 disassembly spans. [Native evidence][disk24-vectors],
[scan receipt][disk24]

## Application consequences and remaining questions

This work strengthens the distinction between the raw running calendar,
software correction, and retained offset/DST metadata. It supplies no basis for
turning raw RTC values into proven UTC timestamps or for rewriting historical
Track dates after a city/DST change. Existing best-effort date conversion and
preservation of raw words remain appropriate; no application code is changed.

For both families, the concrete next seams are the exact semantics of PMU register
`0x58`, earlier BootROM behavior, independently identified raw-clock seed paths
outside the inspected EFI surface, and a full handoff trace. No qualified
Classic BootROM byte image was located for this pass. Physical reset defaults
and power-loss persistence are not inferred from either stubbed native execution
or a related-part datasheet. The newly acquired family 24 plaintext closes the
former input gap. Diagnostic-image execution, computed peripheral access, and
complete boot/handoff scheduling remain untraced for both targets.

Run from the firmware lab using a new destination:

```powershell
uv run scripts/check_classic_early_boot_rtc.py --output-dir artifacts/classic-early-boot-rtc-20261105-v6
uv run scripts/check_classic24_disk_clock.py --output-dir artifacts/classic24-disk-clock-20261105-v3
uv run scripts/check_classic33_disk_clock.py --output-dir artifacts/classic33-disk-clock-20261105-v4
```

The completed [v5 receipt][receipt] records **60 native cases, 44 exact byte
guards, 21 disassembly spans, 82 module hashes**, both IPSW/member identity
checks, both loader-slice matches, and seven family 24 image checksums. The
separate disk artifacts add **12 native cases and 58 word/call guards**.
All checks pass. Originals and shared Ghidra projects remain unchanged.

[previous]: classic-raw-clock-origin-followup-2026-11-05.md
[verifier]: ../../../ipod-firmware-lab/scripts/check_classic_early_boot_rtc.py
[receipt]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/receipt.json
[vectors]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/vectors.json
[pre-entry]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/33-PreEfi-entry.asm
[pre-init]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/33-PreEfi-pmu_init.asm
[pre-io]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/33-PreEfi-pmu_write_read.asm
[ata]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/33-Ata-entry_and_pmu_use.asm
[methods]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/33-DxePcf50635-methods.asm
[registers]: ../../../ipod-firmware-lab/artifacts/hardware-clock-provenance/rockbox/pcf5063x.h
[preparation]: ../../../ipod-firmware-lab/Classic33FW/firmware/analysis-inputs/manifest.json
[acquisition]: ../../../ipod-firmware-lab/notes/session-2026-10-26.md
[rockbox-init]: https://github.com/Rockbox/rockbox/blob/2476968a206e5cdf80fde7887c48cd41512c3276/firmware/target/arm/s5l8702/ipod6g/pmu-6g.c#L435
[aupd-verifier]: ../../../ipod-firmware-lab/scripts/check_classic33_aupd_rtc_surface.py
[aupd]: ../../../ipod-firmware-lab/artifacts/classic33-aupd-rtc-20261105-v1/receipt.json
[disk-verifier]: ../../../ipod-firmware-lab/scripts/check_classic33_disk_clock.py
[disk]: ../../../ipod-firmware-lab/artifacts/classic33-disk-clock-20261105-v3/receipt.json
[disk-startup]: ../../../ipod-firmware-lab/artifacts/classic33-disk-clock-20261105-v3/startup_copy.asm
[disk-restore]: ../../../ipod-firmware-lab/artifacts/classic33-disk-clock-20261105-v3/metadata_restore.asm
[disk-adjusted]: ../../../ipod-firmware-lab/artifacts/classic33-disk-clock-20261105-v3/adjusted_set.asm
[disk-vectors]: ../../../ipod-firmware-lab/artifacts/classic33-disk-clock-20261105-v3/vectors.json

[new-acquisition]: classic-aupd-hardware-acquisition-2026-11-05.md
[vectors24]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/family24-vectors.json
[pre24-entry]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/24-PreEfi-entry.asm
[pre24-init]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/24-PreEfi-pmu_init.asm
[aupd24-pmu]: ../../../ipod-firmware-lab/artifacts/classic-early-boot-rtc-20261105-v5/24-AUPD-pmu.asm
[disk24-verifier]: ../../../ipod-firmware-lab/scripts/check_classic24_disk_clock.py
[disk24]: ../../../ipod-firmware-lab/artifacts/classic24-disk-clock-20261105-v2/receipt.json
[disk24-vectors]: ../../../ipod-firmware-lab/artifacts/classic24-disk-clock-20261105-v2/vectors.json
