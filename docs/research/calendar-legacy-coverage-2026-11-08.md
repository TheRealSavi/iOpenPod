# Calendar coverage for Mini 1, Mini 2 and Nano 1

Investigated 2026-11-08 against original retained firmware. These are bounded
original-instruction experiments with synthetic memory, not physical delivery
or a full document-import test. No device was accessed or modified.

## Exact inputs

| Workspace / RetailOS / updater | OSOS SHA-256 | Corpus manifest SHA-256 |
| --- | --- | --- |
| Mini1FW / 1.4.1 / 3 and 6 | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` | `d32cca7a0c7f5109b1d2a9287b0d3988f131f111e1e17370fb67331d61bcbd7b` |
| Mini2FW / 1.4.1 / 7 | `346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d` | `d8dd483f322ad1513d48c38f3e492e02bb18e50f77a40b7c74aeaa52be6fcc4c` |
| Nano1FW / 1.3.1 / 14 and 17 | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` | `9fd79ed06dbf964e35261cbf8b74ed3b6ca9785970404fe7cdb199eab859e687` |

The lab [Mini 1 workspace][mini1] and [Nano 1 workspace][nano1] establish the
byte-identical updater aliases and independently verified runtime maps. Each
new harness rejects a different OSOS hash and checks initialized memory-block
hashes against its own corpus manifest. Mini 1 and Nano 1 use `evidence/corpus`;
Mini 2 uses `evidence/corpus-v2`. Unicorn 2.1.4 and Capstone 5.0.6 remain research
dependencies only.

## Basic Calendar and names

Mini 1 and Nano 1 have independently exercised native dispatch for Calendar
names, event/To Do children, and summary, description and location properties.
These are more than token-presence observations: each original callback compares
the supplied key or child component and calls the corresponding property route.
The native comparison routines execute unchanged. The generic parser reader is
substituted to supply a synthetic UTF-16 span, and final property consumers are
substituted to record dispatch; this does not establish every text escape or
malformed-document behavior.

| Target | Root callback | Name consumer | Event child | To Do child | Summary / description / location |
| --- | --- | --- | --- | --- | --- |
| Mini 1 | `0x529b4` | `0x81cac` | `0x78ba4` | `0x812a0` | `0x80cbc` / `0x78980` / `0x7b138` |
| Nano 1 | `0xeab28` | `0xeae7c` | `0xeaab4` | `0xeaa40` | `0x12ebe4` / `0x12edc0` / `0x12ecd8` |

The tested properties are `X-WR-CALNAME`, `BEGIN:VEVENT`, `BEGIN:VTODO`,
`SUMMARY`, `DESCRIPTION`, and `LOCATION`. Each target passed six positive native cases and two ignored-property cases.
Mini 1's event callback is `0x52c00`; Nano 1's To Do callback `0x12f124` reuses
the base event text-property path. The Mini 1 name consumer retains the decoded
name through the same structure seen in Mini 2 `0x81fe0`; it is not a filename
or a capacity-derived calendar identity. The original Mini 2 name handler is
[exported here][mini-name-handler]; the Nano 1 name route is inside the
[original root dispatcher disassembly][nano-root-handler]. App source-based grouping remains an
explicit application policy, not a claim about case folding on the iPod.

Receipts: [Mini 1 basic dispatch][mini1-basic], [Nano 1 basic dispatch][nano1-basic].
Original disassembly and automatic pseudocode remain under each workspace's
`evidence/corpus/functions`; some real native entry points are inside Ghidra's
larger function ranges. The probes execute the original addresses directly.

## Recurrence

Mini 1 independently passed the same 720 DAILY/WEEKLY candidate-membership
checks and returned-span comparisons as the earlier [Mini 2 qualification][mini2-rec].
The Mini 1 constructors are `0x94aec` (daily) and `0x951e0` (weekly), the date
constructor is `0xec474`, and event membership is `0x53514`. Only allocator
substitution is reached by the tested recurrence paths. Tests include intervals
1 and 2, COUNT 1 and 3, inclusive UNTIL at the source start time versus one
second before, pre-seed rejection, another weekday, leap day, year crossing and
23:00 starts. Every matched occurrence returns the shifted source start/end span.

This qualifies the same bounded floating same-day whole-second subset for Mini 1.
The source COUNT initialization, default UNTIL and resource bounds remain those
recorded in ADR-0249. It does not transfer arbitrary BY*, exceptions, timezone,
all-day, multiday, monthly/yearly or combined COUNT+UNTIL semantics.

Nano 1 independently passes the same 720 cases. Its concrete native model uses
start/end at `+0x1c` and recurrence at `+0x34`, rather than Mini offsets. Its
constructors are `0x122e10`/`0x122e44`, date initialization/setters are
`0x146208`/`0x1460cc`, and event membership is `0x1a5b80`. The actual native
COUNT initializer `0xf2bd8` retains the 10,000-candidate bound, expressed as
`uVar2 < 0x2000 || uVar2 - 0x2000 < 0x710`. No generic RFC evaluator substitutes
for native membership in these probes. Only allocation is substituted.

Receipts: [Mini 1 recurrence][mini1-rec], [Nano 1 recurrence][nano1-rec].

## Single saved Calendar reminder

All three images independently qualify the existing conservative single
start-relative `VALARM`/`TRIGGER:-PT15M` authoring form. No ACTION or sound field
is needed by the observed parser. Physical arming and delivery remain separate.

| Target | VALARM constructor | Property callback | TRIGGER constructor / evaluation |
| --- | --- | --- | --- |
| Mini 1 | `0xe2b04` | `0x52708` | `0xe62c8` / `0x53a38` |
| Mini 2 | `0xe2c64` | `0x52a54` | `0xe6428` / `0x53d84` |
| Nano 1 | `0xae7a4` | `0xae71c` | `0xdf664` / `0xdf638` |

Each real VALARM constructor creates one wrapper with a null trigger pointer.
These constructor tests substitute only allocation. There is no action selection
in the tested initialization. Each callback then handles `TRIGGER` and `trigger`,
and rejects `ACTION:DISPLAY`, `ACTION:AUDIO`, `REPEAT:3` and `DURATION:PT5M`.
These six callback cases execute the real comparison routine; generic parser
reading and final trigger consumption are explicit substitutions.

Mini 1 and Nano 1 additionally execute their complete real TRIGGER property
construction and evaluation, substituting allocation only. Default and explicit
`RELATED=START` produce mode 1 and signed seconds -900; explicit `RELATED=END`
produces mode 0 and -900. Mini 2's independently executed property construction
is retained in the earlier [Calendar research][earlier]. Authoring remains
start-relative: the END parser result does not qualify missing-end inference or
all scheduling behavior. Absolute, multiple and ambiguous triggers remain
preserved without the new editor rights.

Receipts follow the pattern `.scratch/{mini1,mini2,nano1}-valarm-default-20261108/receipt.json`
and `.scratch/{mini1,mini2,nano1}-valarm-callback-20261108/receipt.json`.
Mini 1 and Nano 1 trigger receipts are `.scratch/mini1-trigger-20261108/receipt.json`
and `.scratch/nano1-trigger-20261108/receipt.json`.

## To Do completion correction

Native To Do constructors initialize the saved status selector to **0**. Status
consumers recognize `COMPLETED` as 2, `IN-PROCESS` as 3, and `CANCELLED` as 4.
`NEEDS-ACTION` leaves a sentinel unchanged and is not recognized on these paths.
Consequently, reopening a To Do should remove STATUS so its next parse retains
the native default, rather than claim a native NEEDS-ACTION token.

| Target | Model constructor | Status consumer | Selector offset |
| --- | --- | --- | --- |
| Mini 1 | `0xe4b08` | `0x80c4c` | model `+0x58` |
| Mini 2 | `0xe4c68` | `0x80f80` | model `+0x58` |
| Nano 1 | `0xc6460` | `0x12f1c4` | model `+0x6c` |

All three constructors and all four status-value cases execute original
instructions with allocator-only substitution. No Host time is needed for a
status-only completion action. The original To Do callbacks additionally return unhandled for a separate
`COMPLETED` timestamp and `PERCENT-COMPLETE:100`, with no final property consumer
called. These negative cases execute the actual callback/comparison paths;
Mini 1 uses `0x52f68`, Mini 2 `0x532b4`, and Nano 1 `0x12f124`. The application
must not manufacture either property as a claimed native completion effect.
Receipts: `.scratch/{mini1,mini2,nano1}-todo-status-20261108/receipt.json`.
The first receipt's descriptive default-case label contains the decimal selector
offset due to harness label substitution; its asserted native zero value is
unchanged. These are private reproducible research artifacts, not application
runtime dependencies.

[mini1]: ../../../ipod-firmware-lab/notes/mini1-firmware-workspace.md
[nano1]: ../../../ipod-firmware-lab/notes/nano1-firmware-workspace.md
[mini2-rec]: calendar-recurrence-qualification-2026-11-08.md
[earlier]: ../../../ipod-firmware-lab/notes/mini2-calendar-alarm-2026-11-06.md
[mini1-basic]: ../../.scratch/mini1-basic-dispatch-20261108-v2/receipt.json
[nano1-basic]: ../../.scratch/nano1-basic-dispatch-20261108-v2/receipt.json
[mini1-rec]: ../../.scratch/mini1-calendar-recurrence-20261108/receipt.json

[nano1-rec]: ../../.scratch/nano1-calendar-recurrence-20261108/receipt.json

[mini-name-handler]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00081fe0.c
[nano-root-handler]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/000eaa40.asm.txt
