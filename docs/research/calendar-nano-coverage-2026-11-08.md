# Nano Calendar firmware coverage

Investigated 2026-11-08 against original retained images. This report distinguishes
native Calendar availability from parser tokens and from qualified Host authoring.
No device was connected or mutated by these probes.

## Nano 6 and Nano 7: explicitly unsupported

The original capability builders execute with a synthetic output sink. Each emits
`iCalendarsSupported=0` and `vCardsSupported=0`. This is positive native evidence
of unsupported Calendar synchronization, rather than an inference from missing
strings. Nano 6 retains Calendar screen strings in its image; those leftovers do
not override the native capability declaration.

| Target | Original OSOS SHA-256 | Executed capability routine |
| --- | --- | --- |
| Nano 6 / updater 36 / 1.2 | `d529680b7e7662876543d70b6941ddfac123d96c8ed1923432e4909909e896d8` | `0x0817b908` |
| Nano 7 / updater 37 / 1.0.4 | `4a55fffbf58cfd04a393e9a40c0c1c42471dfb34d11847b676b85f02a8019999` | `0x081da4dc` |
| Nano 7 / updater 39 / 1.1.2 | `ac4cf072d3c3f971b6acc03ed4f2ad1baa57d7bae20f89692bd6fb08d8a749e4` | `0x081da4e0` |

The routine body executes as original Thumb instructions. Only the output-property
emitter is substituted to record its key and scalar arguments. Input model memory
is zeroed, so the conditional AllVideosSupported branch is not exercised; the
Calendar=false assignments are unconditional. The normal clock/alarm and timer
applications are separate capabilities.

Primary sources are the independently byte-audited exports:
[Nano 6 capability routine](../../../ipod-firmware-lab/Nano6FW/analysis/osos-corpus/functions/0817b908.c),
[Nano 7 1.0.4 routine](../../../ipod-firmware-lab/Nano7FW/analysis/osos-corpus/functions/081da4dc.c),
[Nano 7 1.1.2 routine](../../../ipod-firmware-lab/Nano75FW/analysis/osos-corpus/functions/081da4e0.c).
The reproducible [native harness](../../.scratch/probe_calendar_nano_coverage.py)
and [receipt](../../.scratch/calendar-nano-inventory.json) record exact image and
verified startup-map hashes. Both are private research artifacts, not application
dependencies.

## Nano 2: encrypted evidence remains unknown

Current filesystem inspection confirms `Nano2FW` contains `originals`, `firmware`
and `evidence`, with no accepted plaintext OSOS or Ghidra project. The two updater
19/29 packages share byte-identical firmware 1.1.3. Calendar support must remain
unknown for this native investigation; encrypted bytes cannot qualify an editor.
See the [workspace evidence](../../../ipod-firmware-lab/notes/nano2-firmware-workspace.md).

## Nano 3, Nano 4 and Nano 5: native Calendar consumers

These are independent exact images, not support inferred from the Classic name.
Nano 3 and Nano 4 use their verified startup runtime maps. Nano 4's last eight
uncertain source bytes are outside every executed span. Nano 5 maps the original
raw image's DRAM region at source `0x2e27c` to runtime `0x08000000`, following its
existing independently verified native harness.

| Target | Original OSOS SHA-256 | Calendar token table |
| --- | --- | --- |
| Nano 3 / updater 26 / 1.1.3 | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` | `0x083caea4` |
| Nano 4 / updater 31 / 1.0.4 | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` | `0x0837e0e4` |
| Nano 5 / updater 34 / 1.0.2 | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` | `0x0844cb18` |

Primary mapping sources:
[Nano 3 runtime map](../../../ipod-firmware-lab/Nano3FW/evidence/runtime-map.json),
[Nano 4 runtime map](../../../ipod-firmware-lab/Nano4FW/evidence/runtime-map.json),
[Nano 5 original native image loader](../../../ipod-firmware-lab/scripts/probe_nano5_chapter_artwork.py).

### Basic Calendar and name dispatch

The [dispatcher harness](../../.scratch/probe_calendar_nano_dispatch.py) executes
69 independent original-instruction cases across the three images. Its
[receipt](../../.scratch/calendar-nano-dispatch.json) pins image hashes, runtime
spans and tested-span hashes. ASCII key comparison and generic property-value
reading are explicit adapters; the selected downstream handler is recorded rather
than simulated as a full filesystem import.

| Target | Calendar callback | Event property callback | Name handler |
| --- | --- | --- | --- |
| Nano 3 | `0x0815a468` | `0x081cfc0c` | `0x0815a7bc` |
| Nano 4 | `0x0813e49c` | `0x0819878c` | `0x0813e6ba` |
| Nano 5 | `0x0807bacc` | `0x080fdf5c` | `0x08097922` |

All three handle Calendar `X-WR-CALNAME`, `VERSION` and `PRODID`, and event
`SUMMARY`, `DESCRIPTION`, `LOCATION`, `DTSTART`, `DTEND` and `RRULE`. An unknown
property returns unhandled. Name dispatch reads the token-table offset `+0xd0`;
this is an executed consumer, not just the presence of a string. Nano 3's name
handler assigns the captured name and calls the named-collection lookup/create
path at `0x0815a754`. The basic event and name editor can therefore use the
existing lossless Calendar writer on these exact targets. This does not qualify
arbitrary RFC extensions or individual-occurrence edits.

### Saved Calendar reminders

Each original `VALARM` property callback handles `TRIGGER` and rejects `ACTION`,
`REPEAT` and `DURATION`. The trigger parser constructors initialize anchor `1`
(start), a null trigger pointer and an unset absolute-date flag. There is no
requirement to invent an `ACTION` or sound for the saved trigger.

| Target | VALARM callback | Trigger constructor | Duration leaf | Relative consumer |
| --- | --- | --- | --- | --- |
| Nano 3 | `0x081107bc` | `0x0814d044` | `0x080a1270` | `0x0814cfcc` |
| Nano 4 | `0x0810aa9c` | `0x08136614` | `0x080abf8c` | `0x081365cc` |
| Nano 5 | `0x0813ce10` | `0x08155000` | `0x082475e4` | `0x0816d44c` |

The [reminder harness](../../.scratch/probe_calendar_nano_reminders.py) and
[receipt](../../.scratch/calendar-nano-reminders.json) execute 15 pairs of native
duration/relative-consumer cases plus constructor-default checks. Inputs are
`-PT15M`, `PT0M`, `-P7D`, `P2DT3H4M5S` and `-P1DT1H`. Every exact image returns
respectively minus 900 seconds, zero, minus seven days, two days plus 11,045
seconds, and minus one day minus 3,600 seconds. The native relative consumer
combines days and seconds into the signed scalar and passes the start anchor to
the trigger constructor. Decimal conversion, final object allocation/construction
and pointer adoption are recorded adapters; original duration control flow,
signs, day arithmetic and anchor forwarding execute.

This supports the same conservative single start-relative, whole-minute saved
reminder editor already used for Classic. The application's one-week input cap
is an application limit. Multiple reminders, absolute triggers, subminute values,
end-relative authoring and physical notification delivery are separate questions.
No wake, sound or live firmware adoption was physically tested.

### To Do completion uses the native status field

The three actual VTODO property callbacks handle `DUE` and `STATUS`; they delegate
other properties to their entry base. The base callbacks independently reject
`COMPLETED` and `PERCENT-COMPLETE` properties. Those properties therefore must not
be invented by an iPod completion action.

| Target | VTODO callback | Status value handler | Entry constructor |
| --- | --- | --- | --- |
| Nano 3 | `0x081cfc0c` | `0x081cfcac` | `0x0812b6e0` |
| Nano 4 | `0x08198db8` | `0x08198e18` | `0x0811fbdc` |
| Nano 5 | `0x080ed9f4` | `0x080fe1c0` | `0x081e1f4c` |

The [To Do harness](../../.scratch/probe_calendar_nano_todo.py) and
[receipt](../../.scratch/calendar-nano-todo.json) execute 18 independent cases.
Original constructors zero the status word at entry `+0x6c`, even when object
memory initially contains `0xff`. External member-subobject initializers are
stubbed to return their input pointer, leaving native field initialization intact.
The original handlers store status `2` for `COMPLETED`, `3` for `IN-PROCESS` and
`4` for `CANCELLED`; `NEEDS-ACTION` and an unknown value leave the default `0`
unchanged. The status setters on Nano 4/5 also execute as original instructions.
Removing an existing STATUS property when reopening a To Do therefore selects
the native fresh default on reparse. Completing it needs `STATUS:COMPLETED` only.
Unrelated imported unknown properties remain preserved by the byte writer.

### Advanced rule inventory is not complete semantic qualification

All three exact token tables and property dispatchers include daily, weekly,
monthly and yearly recurrence, INTERVAL, COUNT, UNTIL, WKST, BYDAY, BYSETPOS,
BYMONTHDAY, BYYEARDAY, BYMONTH, BYWEEKNO, RDATE and EXDATE. Nano 3's frequency
selector `0x081eff98` and Nano 4's `0x081b553c` map DAILY/WEEKLY/MONTHLY/YEARLY
to native selectors 4/5/6/7. Rule-property callbacks are `0x081f03cc` and
`0x081b57b0`. These are consumers rather than mere token sightings, but parser
dispatch still does not establish each recurrence's occurrence semantics.

Read-only Ghidra exports of the selected consumers are retained in
[the Nano 3 export](../../.scratch/calendar-nano3-functions.c) and
[the Nano 4 export](../../.scratch/calendar-nano4-functions.c). Some untouched
Thumb functions fail automatic decompilation; direct instruction disassembly and
native execution take precedence over truncated pseudocode. The Nano 5 existing
project was locked during this pass, so it was left untouched; its original bytes
were inspected and executed directly. Recurrence-specific execution receipts
are recorded in the [Classic/Video and Nano 3/4 qualification](calendar-classic-video-coverage-2026-11-08.md)
and the Nano 5 result below.

## Qualified Nano 5 occurrence semantics

The separate [native recurrence harness](../../.scratch/probe_calendar_nano5_recurrence.py)
completed **1,920 original-instruction event-membership checks** for updater 34 /
1.0.2. The [receipt](../../.scratch/calendar-nano5-recurrence-native.json) binds
original raw OSOS SHA-256
`dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49`,
the runtime map, the harness hash and hashes of every executed instruction span.
The runtime DRAM map is source `0x2e27c`, length `0x6c43a8`, at `0x08000000`;
IRAM and IRAM2 mappings are separately recorded. The callback addresses below
are instruction addresses; the receipt adds the Thumb low bit when calling them.

| Native role | Address |
| --- | --- |
| Frequency object factory | `0x0812c344` |
| DAILY factory / direct constructor | `0x081355b8` / `0x0813e63c` |
| WEEKLY factory / direct constructor | `0x081355d6` / `0x0813e72c` |
| Civil-date constructor | `0x082605b8` |
| Full event candidate membership | `0x081a9558` |

Original constructors, civil-date construction, COUNT initialization, event seed
guarding and returned event-span construction execute. There are no substituted
calls in these occurrence probes. Event objects and candidate dates reside in
synthetic memory; this is not a full Calendar file import or hardware test.

Four seeds cover Sunday and Wednesday, a leap-day crossing and a year crossing.
For DAILY and WEEKLY, cases cover intervals 1 and 2, COUNT 1 and 3, no COUNT,
and UNTIL at the exact event-start second or one second earlier. Forty
candidate dates per case include two days before the seed. Native membership
rejects pre-seed candidates, includes the seed, honors the tested interval/count
limits and treats UNTIL as inclusive at the occurrence start. Every successful
query returns the exact candidate day's original 09:00–10:00 event span.

This independently qualifies Nano 5 for the same bounded floating, same-day
DAILY/WEEKLY application subset. It does not qualify monthly/yearly corner cases,
BY* constraints, date-only or zoned recurrence, exception expansion, multi-day
events, combined COUNT+UNTIL or individual-occurrence authoring. Nano 3 and Nano 4
have their own 1,920-case full event-span checks in the linked qualification;
none receives occurrence semantics solely from Nano 5 code similarity.
