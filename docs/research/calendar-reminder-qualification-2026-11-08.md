# Qualified Calendar reminder editing subset

Investigated 2026-11-08 against retained original firmware. This continues the
[Calendar/Alarm research](calendar-alarm-firmware-2026-11-06.md). It qualifies
saved Calendar reminder representation, separately from physical delivery,
Clock Alarm records, Sleep Timer control and Host notifications.

## Implementation decision supported by this evidence

For the four exact Classic targets below, a conservative authoring subset is one
nested `VALARM` with a relative `TRIGGER` associated with the event start. No
invented `ACTION:DISPLAY`, `ACTION:AUDIO`, sound identifier, repetition count or
notification delivery mode is needed by the observed native parser.

```text
BEGIN:VALARM
TRIGGER:-PT15M
END:VALARM
```

The original trigger constructor defaults to the start anchor. Explicit
`RELATED=START` and `RELATED=END` parameter stores were already exercised in the
earlier per-image probes. End-relative authoring should require an explicit,
supported event end; missing-end inference is not qualified. The simplest first
editor can expose start-relative reminders only and preserve other forms.

Editing an existing qualified trigger must preserve unrelated bytes and unknown
properties. Multiple `VALARM` children or repeated/ambiguous `TRIGGER` properties
should remain read-only in a single-reminder editor. Absolute triggers must remain
read-only because the observed native leaf loses the separate `Z` marker before
construction, and later timezone interpretation remains unresolved.

This qualification does not establish when a published file is adopted, that the
device is armed, or that a reminder will wake the device or play sound. Product
text should describe a saved Calendar reminder rather than promise delivery.

## Exact targets

| Updater / RetailOS | Original plaintext OSOS SHA-256 | VALARM callback | Constructor |
| --- | --- | --- | --- |
| 24 / 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` | `0x080fdce4` | `0x080fdd6c` |
| 33 / 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | `0x081022ec` | `0x08102374` |
| 35 / 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | `0x08119688` | `0x08119710` |
| 38 / 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | `0x0811987c` | `0x08119904` |

Addresses are runtime addresses, not file offsets. The new probes load and hash
each image independently through the lab's [Image reader][reader]. Their receipt
also records the memory-map path/hash and the hash of each tested instruction
span. No retail generation label substitutes for those exact inputs.

Mini 2 / 1.4.1 and Video families 13/20/25 / 1.3 have independently executed
relative/absolute trigger construction evidence in the earlier research. This
pass did not trace their complete `VALARM` property callback and action/default
paths to the same depth. Do not automatically grant them this new authoring
qualification merely because their trigger objects look similar.

## New native and static findings

### VALARM recognizes TRIGGER without an action property

Each independently inspected Classic callback reads its actual token table at
offset `+0xac`, whose string is `trigger`. It compares the supplied property name,
calls a trigger handler on a match, and returns unhandled on a mismatch. No branch
in these callback bodies tests `ACTION`, `REPEAT`, or `DURATION`.

The new harness executes the original callback instructions for these inputs:

| Property/value | Callback result | Trigger handler invoked |
| --- | --- | --- |
| `TRIGGER:-PT15M` | Handled | Yes |
| `trigger:-PT15M` | Handled under the explicit ASCII comparison adapter | Yes |
| `ACTION:DISPLAY` | Unhandled | No |
| `ACTION:AUDIO` | Unhandled | No |
| `REPEAT:3` | Unhandled | No |
| `DURATION:PT5M` | Unhandled | No |

The key-comparison adapter, generic property-reader operation and final trigger
construction call are explicitly substituted in these dispatcher probes. They
isolate the original dispatch behavior; they are not a full XML/iCalendar parser
emulation or a new proof of the native comparison routine's Unicode behavior.
The earlier tests separately execute the original relative-duration leaf and
parameter consumers, including `-PT15M` becoming minus 900 seconds.

### Constructors and adoption

Each original `VALARM` constructor installs a vtable whose property-callback
pointer matches the separately identified callback above. It allocates a small
trigger wrapper and initializes its trigger pointer to null. The probes execute
the original constructor and wrapper initializer with explicit allocator,
base-parser and reference-adoption adapters. There is no action selection in the
tested subclass initialization or property dispatch.

For Classic 33, the inspected event route at `0x081b764c` creates the `VALARM`
parser, parses its component, and adopts its result through `0x0811de5c` into the
event's single reminder slot at `+0x30`. The validity query `0x08273d54` checks
whether the trigger pointer is non-null. The trigger holder setter at
`0x08134cf8` replaces its prior pointer. This is supporting static evidence for a
single-trigger subset; it is not a promise of multiple independent reminders.

The Classic-33 [constructor export][constructor] and
[event adoption export][adoption] are Ghidra-derived pseudocode, with inferred
types and research names. The new investigation also directly disassembles the
original bytes rather than relying on those inferred types. Other targets are
qualified by their own tested callback and constructor instructions, not by
assuming the Classic-33 addresses relocate uniformly.

## Existing trigger evidence retained

The [earlier Classic receipt][classic-receipt] independently executes signed
relative-duration and trigger-parameter consumers for all four exact images:

- `-PT15M` reaches the relative constructor as minus 900 seconds.
- `RELATED=START` stores selector 1; `RELATED=END` stores selector 0.
- The constructor defaults to selector 1 and relative mode.
- Days combine with seconds using 86,400 seconds per day.
- `P2W` produces zero in the tested leaf, while `P1M` produces 60 seconds;
  standard-looking duration strings must not be expanded with an RFC library
  and assumed to have native parity.

An authoring implementation should emit a narrow numeric minutes/seconds form,
validate its arithmetic bounds, and preserve unsupported retained spellings.
It should not silently normalize week durations or absolute trigger timezone
state. The [Mini report][mini] and [Video report][video] independently record
similar relative-trigger construction and the remaining delivery questions.

## Reproduction and limits

The bounded new probe is retained privately as
`.scratch/probe_calendar_reminder_subset.py`; its JSON receipt is
`.scratch/calendar-reminder-qualification-2026-11-08.json`. From the iOpenPod root:

```powershell
uv run --with capstone==5.0.6 --with unicorn==2.1.4 python .scratch/probe_calendar_reminder_subset.py
```

Observed result: **28 native cases passed across four exact Classic images**
(six property-dispatch cases and one constructor/default case per image).
The helper imports pinned lab readers without adding a runtime dependency to
iOpenPod. Inputs are read-only; output contains identities, span hashes and
scalar observations rather than firmware copies. No device, firmware
installation or existing Ghidra project was changed.

No full-file firmware import, complete scheduler, hardware wake, audible output,
missed-reminder behavior, repeat delivery or physical-device acceptance was
executed. Those remain separate evidence gates and must not be represented as
features established by these saved-format tests.

[reader]: ../../../ipod-firmware-lab/scripts/check_classic_clock_observers.py
[constructor]: ../../../ipod-firmware-lab/artifacts/classic-calendar-parser-20261106-v1/08102374-FUN_08102374.c
[adoption]: ../../../ipod-firmware-lab/artifacts/classic-calendar-parser-20261106-v1/0811de5c-FUN_0811de5c.c
[classic-receipt]: ../../../ipod-firmware-lab/artifacts/classic-calendar-native-20261106-v6/receipt.json
[mini]: ../../../ipod-firmware-lab/notes/mini2-calendar-alarm-2026-11-06.md
[video]: ../../../ipod-firmware-lab/notes/video-calendar-alarm-2026-11-06.md
