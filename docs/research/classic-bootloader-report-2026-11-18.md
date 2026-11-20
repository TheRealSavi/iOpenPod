# Classic bootloader report, 2026-11-18

## Result and evidence boundary

The 0.6.0-dev common firmware measures the installed plaintext bootloader and
reports it through normal USB. The packaged bootloader remains 2.1.0. This change
has passed offline ARM execution, transport simulations and application tests;
it has **not been installed or physically tested** in this development run.

The existing shared loader is format 2: its executable in NOR is plaintext, even
though its installation header is personalized by the iPod. Format-1 encrypted
OEM loaders cannot be identified by this reader and return an explicit encrypted
status. A missing custom marker means unrecognized, not proven stock.

## Native path

`scripts/firmware/classic_about/entry.S` invokes `iop_boot_report_capture` after
copying initialized mod code and zeroing mod BSS, before Apple's entry at
`0x22000000`. Apple clears BSS below the Mod Memory Region at `0x08b3c000`.
There are no OS tasks, heap calls or native SPI-driver ownership to race here.

The reader adapts the pinned Rockbox SPI sequence already used by the DFU helper.
It masks IRQ/FIQ, saves SPI/GPIO/clock configuration, checks NOR status and reads
SysCfg followed by the loader. Commands are limited to `0x05` and `0x03`; there
are no program, erase, write-enable or flash-status writes. One shared 8,000,000
poll budget bounds failed/absent hardware. Cleanup deasserts chip select and
restores configuration and interrupt masks, including on early failure.

SysCfg occupies the first 8 KiB. Validate its header and bounded 20-byte entries,
requiring unique `SrNm`, `Mod#` and `HwVr`. Hardware revision is the second word
of the HwVr value, not its first word. Family revisions are `0x130000`, `0x130100`,
`0x130200`, `0x130300` for 24, 33, 35, 38 respectively.

The bootloader header starts at NOR `0x8000`; its body is
`[0x8800, 0x28000)`, 129,024 bytes. Require the known `87021.0` header, body size
and format. Stream SHA-256 with a 256-byte buffer. Read the established marker
slots shared with the host decoder; reject duplicates. The retained result is
136 bytes. The linked release uses 109,496 initialized bytes and reserves
114,688 bytes of RAM, one 4 KiB page more than 0.5.0-dev.

Apple's SysInfo generator at `0x08145938` closes its root dictionary via the
`bl 0x08118cf0` at `0x081477f4` (preimage `3d45ffeb`). Replace that single call
with the report wrapper, then execute the original close. The next plist-close
call remains intact. Native writers at `0x08118a14`, `0x0811891c`, `0x08118b50`
and `0x08118cf0` supply dictionary, integer, escaped string and close operations.
The caller at `0x08147930` retries with more space using the writer's missing-byte
count. The report adds under 1 KiB and uses this existing allocation path.
The previously retained normal-mode SysInfo payload is 12,464 bytes; adding the
entire 791-byte probe XML as a conservative upper bound gives 13,255 bytes,
below the native 15,376-byte limit and the existing VPD page range. This uses a
saved capture for sizing, not a new physical response from the modified firmware.

## Wire contract and host decision

The nested `iOpenPodBootReport` dictionary contains:

| Field | Meaning |
| --- | --- |
| Schema | Integer 1 |
| Status | 1 read error, 2 unsupported, 3 encrypted, 4 measured |
| ModVersion | Independent firmware platform version |
| DeviceSerial / DeviceModel | SysCfg identity; supplied for statuses 3 and 4 |
| HardwareRevision | SysCfg hardware word; supplied for statuses 3 and 4 |
| BodySHA256 | Lowercase 64-digit hex; measured status only |
| Marker | Complete 64-byte record as 128 hex digits; measured status only |

An absent marker is represented by zero bytes. The host represents invalid
reports separately from absent reports. It rejects malformed types, duplicate
keys, unknown schema/status, identity mismatch and oversized XML. Saved metadata
files cannot provide this evidence. Discovery refresh replaces the current report,
even if the OS version and updater family are unchanged.

Install eligibility requires the measured executable SHA-256
`7d4e94a6a509713d92e3d54f839491e4152a2fb639fb178ad50d2aaf38abbe61`,
marker schema/ABI 2, target `CLSC`, hardware mask 15 and release `2.1.0`.
Both marker and full body must match. An old receipt cannot override a negative
current report. The installer rereads inside its retained SCSI Session before
the first write. No new device-write path exists outside Storage.

## Reproduction and validation

Build using `scripts/firmware/README.md` with `--bootloader-report` and version
`0.6.0-dev`. Complete image: 101,871,616 bytes, SHA-256
`9d4c9852b737f8ca59401275b033c4a2c8a9d3b2dac35ab8a3351a32ce102701`.
The bootloader source and assets are unchanged.

The research checkout's `scripts/probe_classic_boot_report.py` executes the actual
compiled reader, SHA implementation and Apple XML writers under Unicorn. It models
NOR/SPI input with the qualified loader and synthetic device identity. It covers
all four hardware families, encrypted and malformed headers, bad SysCfg, absent
and duplicate markers, busy/AAI status, polling exhaustion, register restoration,
small XML buffers and repeated serialization with no further NOR reads.
For the timeout test only, the model reduces the remaining poll counter to 32;
the production bound stays unchanged. Bootstrap tests at load origins `0x09000000`
and `0x08000000` verify overlapping copy, report survival across Apple's BSS clear
and preservation of incoming registers/stack. All cases passed.

`tests/fixtures/firmware/classic-boot-report.xml` is an actual native-writer output
using synthetic serial TEST12345678 and family-33 model MB565. Host tests exercise
its parser, current-over-historical precedence, receiptless installation and
zero update commands on negative reports. Hardware timing and real boot/USB
behavior still require a physical trial; emulation does not establish those.
