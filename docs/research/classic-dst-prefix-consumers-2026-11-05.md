# Classic DST prefix consumers

Research date: **2026-11-05, America/Detroit**. This pass investigates the two
leading bytes in `iPod_Control/Device/dst` for updater family **35 / RetailOS
2.0.4** and **38 / RetailOS 2.0.5**, with **33 / 2.0.1** and **24 / 1.1.2** as
separate controls.

The two bytes remain **opaque ordered bytes**. The inspected later loaders copy
them into a global destination, then load a fixed 3,280-byte rule region. The
identified rule consumers use fixed 205-row bounds and never interpret that
prefix. Native ARM probes confirm that changing the prefix does not change
either loader selection or the enabled-rule lookup within the tested scope.
No numeric byte order, format version, rule count, checksum or update sequence
meaning has been established. This strengthens the existing preservation model;
it does not justify rejecting any prefix value or blocking a Library workflow.
[ADR-0240](../adr/0240-treat-calendar-dates-as-best-effort-metadata.md),
[ADR-0241](../adr/0241-inspect-firmware-dst-rules-as-optional-evidence.md).

## Inputs, reproducibility and evidence levels

| Updater / release | Logical OSOS SHA-256 | Runtime map |
| --- | --- | --- |
| 35 / 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | [35 startup map][map35] |
| 38 / 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | [38 startup map][map38] |
| 33 / 2.0.1, normalized image | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | [33 normalized map][map33] |
| 24 / 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` | [24 startup map][map24] |

The new [guarded lab script][script] checks each full image hash before analysis.
The retained [receipt][receipt] records map, reference-index and script hashes;
exact instruction bytes; exported span hashes; tool versions; and 24 native
probe cases. It used Python 3.12, Capstone 5.0.6 and Unicorn 2.1.4. Reproduce into
a new directory, without changing the retained evidence:

```powershell
uv run scripts/check_classic_dst_prefix_consumers.py --output-dir artifacts/classic-dst-prefix-20261105-v4
```

Static claims below use primary firmware bytes and their reconstructed memory
maps. Upstream Ghidra reference indexes are discovery hints; each selected
instruction is re-read from the pinned image. Native probes execute only the
identified loader and enabled-lookup instructions. File, text and object
services are mocked, execution outside an explicit function/service allowlist
fails, and a 10,000-instruction limit prevents unbounded execution. This is not
whole-OS emulation or physical acceptance evidence. No iPod was accessed,
clock changed, device file written or shared Ghidra project modified.
[Script][script], [receipt][receipt].

## What receives the prefix

The adjacent globals can be separated by their actual load/store offsets:

| Coordinate | Family 35 address | Family 38 address | Verified use |
| --- | --- | --- | --- |
| Base `+0..1` | `089cb448` | `089d3aa0` | Destination of the initial two-byte file read |
| Base `+2..3` | `089cb44a` | `089d3aa2` | No assigned meaning in this pass |
| Base `+4` | `089cb44c` | `089d3aa4` | Pointer to the allocated city-record copy |
| Base `+8` | `089cb450` | `089d3aa8` | Selected DST-rule table pointer |
| Base `+12` | `089cb454` | `089d3aac` | Separate neighboring object initialized by another routine |
| Base `+16` | `089cb458` | `089d3ab0` | Start of compiled 205-row DST table |
| Custom-row buffer | `08a77fa0` | `08a805f8` | Replacement rule rows loaded from file offset two |

All 16 bytes preceding the compiled table are zero in each initialized firmware
image. This is an image default, not evidence that a file must start with `0000`.
The loader requests two bytes into base `+0`; it performs no halfword load,
byte swap or comparison of those bytes. Consequently, the proven width is a
two-byte transfer, and the proven order is the original file byte order. Calling
the value `u16le` or `u16be` would add an unproven numeric interpretation.
[35 subsystem][state35], [38 subsystem][state38], [state-byte assertions][receipt].

## Loader, bounds and reload behavior

| Operation | Family 35 | Family 38 |
| --- | --- | --- |
| Loader entry | `080f4a38` | `080f4af0` |
| Set fixed row-read size to `0xcd0` | `080f4a54` | `080f4b0c` |
| Prefix read call, requested length two | `080f4ab0` | `080f4b68` |
| Seek call, absolute offset two | `080f4ac4` | `080f4b7c` |
| Row read call | `080f4ad8` | `080f4b90` |
| Test final row-read status | `080f4adc` | `080f4b94` |
| Enabled lookup entry / fixed 205-row comparison | `080f49fc` / `080f4a24` | `080f4ab4` / `080f4adc` |
| City count getter, literal 205 | `080f4b28` | `080f4be0` |
| Active-rule predicate / fixed 205-row comparison | `080f4fc8` / `080f50c0` | `080f5080` / `080f5178` |

Missing-file selection points base `+8` at the compiled rows. An existing file
causes the prefix read, an absolute seek to offset two, then the fixed row read.
Only the final row-read status selects compiled versus custom rows. Neither the
prefix-read status nor seek status is tested, and neither returned byte count
is used to establish completeness. No inspected path clears the prefix during
fallback. The rule builder reads the selected pointer at base `+8`; it does not
read the prefix. [35 subsystem][state35], [38 subsystem][state38].

The enabled lookup and active-rule predicate each contain an immediate `0xcd`
loop bound. The builder addresses a row with `index << 4`. These are independent
positive evidence for the 205 × 16 contract; it is not inferred from a supposed
header count or from the length of one file. The fixed city-count getter is
additional evidence, but is not substituted for inspecting both DST loops.
[35 subsystem][state35], [38 subsystem][state38].

The previously inspected complete [35 read wrapper][read35] and
[38 read wrapper][read38] can cap an oversized request to a positive remaining
length and report success after that shorter transfer. The corresponding
[35 seek wrapper][seek35] and [38 seek wrapper][seek38] reject seeking past EOF
without advancing the position. The native probes model those documented
service outcomes; they do not execute a filesystem driver.

## Reference and writer audit

For each later image, the script scans every raw byte position for little-endian
32-bit addresses pointing into base `+0..16`, then scans initialized mapped
regions for aligned ARM PC-relative loads of the resulting literals. It finds
ten literal words and ten corresponding loads per image: eight base pointers,
one base `+12` pointer and one compiled-table base `+16` pointer. All ten are
accounted for by the following inspected routines. [Receipt][receipt].

| Identified use | Family 35 routine | Family 38 routine | State used |
| --- | --- | --- | --- |
| Transition builder | `080f460c` | `080f46c4` | Reads `+8` |
| Enabled-rule lookup | `080f49fc` | `080f4ab4` | Reads `+8` |
| File loader | `080f4a38` | `080f4af0` | Passes `+0` as read destination; writes `+8` |
| Indexed city access | `080f4c10` | `080f4cc8` | Reads `+4` |
| City identifier search | `080f4c8c` | `080f4d44` | Reads `+4` |
| City-copy initialization | `080f4e58` | `080f4f10` | Reads/writes `+4` |
| City-copy release | `080f4f90` | `080f5048` | Reads/writes `+4` |
| Active-rule predicate | `080f4fc8` | `080f5080` | Reads `+8` |
| Neighboring object initializer | `082a2980` | `082a4264` | Stores through `+12`, not the prefix |

The Ghidra indexes supply 28 references into base `+0..15` per image. Their
actual instructions agree with the classification above: one parameter
reference passes the prefix destination to the read service, and all indexed
reads/writes target `+4` or `+8`. The separate `+12` initializer is found by the
independent literal scan, illustrating why the index alone is insufficient.
Its visible store is through the distinct `+12` destination. The later
initializers are exported as primary-byte evidence, without assigning a date
meaning to the neighboring object. [Receipt][receipt],
[35 neighboring initializer][neighbor35], [38 neighboring initializer][neighbor38].

An independent aligned ARM direct-branch scan finds one branch to each loader:
`0805d774` in 35 and `0805d810` in 38. The retained caller windows show ordinary
calls without any prefix check around them. Each image also contains one copy
of the exact `iPod_Control\Device\dst` path used by this loader. No separate
prefix getter, comparator, numeric decoder, updater or outbound file writer
was identified among these references and consumers.
[35 caller][caller35], [38 caller][caller38], [receipt][receipt].

This is a bounded reference closure, **not proof of whole-program absence**.
Computed addresses, unrecognized Thumb code, indirect callers, dynamically
constructed paths, another executable or Host software could escape these
searches. The single direct caller does not establish when every reload happens.
The exact string search does not prove that no writer exists. In particular,
this pass has not established which Apple Host component generates the prefix.

## Native probe results

Each case starts a fresh machine with the exact image mappings. The destination
prefix is deliberately seeded with `a6b7`, and the custom-row buffer with `a5`
bytes, making retained memory visible. File-service outcomes below are explicit
mock inputs; loader decisions and enabled-lookup results are native execution.
[Script][script], [receipt][receipt].

| Probe, run independently on both images | Native result |
| --- | --- |
| Six complete files beginning `0000`, `0100`, `0001`, `cd00`, `00cd`, `ffff` | Same two-byte read, absolute seek two, 3,280-byte row read, and custom selection |
| Change row 205 enabled byte to `7f` | Lookup returns `7f` for city 205 with every tested prefix |
| Append a valid 206th row | Loader leaves its destination tail untouched; after separately seeding that row in RAM, lookup still ignores city 999 in row 206 |
| Inject prefix-read failure, then successful row read | Custom rows selected; seeded prefix `a6b7` retained |
| Successful prefix read, then injected row-read failure | Compiled rows selected; copied prefix `1234` retained |
| One-byte file | Prefix becomes `12b7`; failed seek and empty row-read outcome lead to compiled rows |
| Prefix plus only 17 row bytes, with positive short-read success | Custom rows selected; unread suffix retains the seeded `a5` memory |
| Missing file | Compiled rows selected; seeded prefix retained |
| Load `ffff`, then call the loader again with missing-file outcome | Compiled rows selected on reload; previous `ffff` prefix remains |

CPU memory-read hooks observe no read of either prefix byte during any executed
loader or enabled lookup. All 24 cases pass. The appended-row test separates
the loader's fixed read length from the lookup's independent fixed iteration
bound. The malformed-file probes explain uncertainty; they are not a claim
that malformed files are safe to install on a real iPod.

## Controls and application consequences

Family 33's independently exported loader at `080dd958` requests 3,280 bytes
directly from the beginning of the file, with no preceding two-byte transfer or
seek. It remains a distinct headerless profile. Family 24 has no occurrence of
the exact later path in the pinned image; previous work also did not establish
an equivalent custom-file consumer. That negative signature result does not
prove the absence of DST features, and 24 remains unqualified for this custom
DST document format. [33 control][control33],
[earlier family comparison](firmware-dst-data-and-city-identity-2026-11-06.md),
[receipt][receipt].

The safe application model is therefore unchanged in substance:

1. Preserve the prefix as exactly two opaque bytes for explicitly qualified
   35/2.0.4 and 38/2.0.5 profiles. Do not normalize, range-check, decode a count
   from it or infer a version from it.
2. Keep the fixed 205 ordered rows and every trailing byte. Complete captured
   rows are interpretable evidence; missing bytes cannot be recreated from
   firmware's unknown prior memory.
3. Distinguish captured file evidence from native active-table state. Even a
   memory prefix can survive fallback, so prefix equality cannot prove that a
   custom table is currently selected or current.
4. Retain independent headerless 33 support and unqualified 24 handling. Never
   infer qualification from file length or from prefix values.
5. Keep missing, short, unsupported or unreadable datetime metadata nonblocking.
   This research adds no grounds for preventing a Library load or Sync and no
   grounds for using annual rules as historical UTC truth.

Remaining questions are the prefix producer and its intended numeric or opaque
meaning, any use outside the inspected subsystem, complete indirect reload
scheduling, and physical acceptance of a controlled custom file. None needs to
be guessed to preserve and inspect existing data safely.

[map35]: ../../../ipod-firmware-lab/Classic35FW/evidence/runtime-map.json
[map38]: ../../../ipod-firmware-lab/Classic38FW/evidence/runtime-map.json
[map33]: ../../../ipod-firmware-lab/vendor/osos-lab/ghidra/profiles/classic6g-reva-2.0.1.json
[map24]: ../../../ipod-firmware-lab/Classic24FW/evidence/runtime-map.json
[script]: ../../../ipod-firmware-lab/scripts/check_classic_dst_prefix_consumers.py
[receipt]: ../../../ipod-firmware-lab/artifacts/classic-dst-prefix-20261105-v3/receipt.json
[state35]: ../../../ipod-firmware-lab/artifacts/classic-dst-prefix-20261105-v3/35-080f460c-state_consumers.asm.txt
[state38]: ../../../ipod-firmware-lab/artifacts/classic-dst-prefix-20261105-v3/38-080f46c4-state_consumers.asm.txt
[neighbor35]: ../../../ipod-firmware-lab/artifacts/classic-dst-prefix-20261105-v3/35-082a2980-neighbor_object_initializer.asm.txt
[neighbor38]: ../../../ipod-firmware-lab/artifacts/classic-dst-prefix-20261105-v3/38-082a4264-neighbor_object_initializer.asm.txt
[caller35]: ../../../ipod-firmware-lab/artifacts/classic-dst-prefix-20261105-v3/35-0805d734-loader_caller.asm.txt
[caller38]: ../../../ipod-firmware-lab/artifacts/classic-dst-prefix-20261105-v3/38-0805d7d0-loader_caller.asm.txt
[control33]: ../../../ipod-firmware-lab/artifacts/classic-dst-prefix-20261105-v3/33-080dd958-headerless_control.asm.txt
[read35]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic35-0826d5e0-read.asm.txt
[read38]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic38-0826eeb0-read.asm.txt
[seek35]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic35-0826d8e0-seek.asm.txt
[seek38]: ../../../ipod-firmware-lab/artifacts/dst-family-formats-20261106-v4/classic38-0826f1b0-seek.asm.txt
