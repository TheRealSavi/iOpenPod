# Classic and Video Calendar feature qualification

Investigated 2026-11-08 against all seven retained latest Classic and Video
inputs. This extends the [Mini recurrence qualification](calendar-recurrence-qualification-2026-11-08.md),
[Classic reminder qualification](calendar-reminder-qualification-2026-11-08.md),
and the lab's [Video](../../../ipod-firmware-lab/notes/video-calendar-alarm-2026-11-06.md)
and [Classic](../../../ipod-firmware-lab/notes/classic-calendar-alarm-2026-11-06.md)
Calendar investigations. No physical iPod was accessed or modified.

## Exact-image coverage

All addresses are runtime ARM addresses, not assumed file offsets. Each Classic
uses its own verified relocation map. Each Video instance executes its own native
startup copy/zero routine at `0x00083848`; the retained startup map is therefore
not replaced by copying an assumed initialized-data tail.

| Target | Original plaintext OSOS SHA-256 | Event membership | Daily constructor | Weekly constructor |
| --- | --- | --- | --- | --- |
| Video 13 / 1.3 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` | `0x00252340` | `0x001abb1c` | `0x001c23d8` |
| Video 20 / 1.3 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` | `0x00252340` | `0x001abb1c` | `0x001c23d8` |
| Video 25 / 1.3 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` | `0x00252340` | `0x001abb1c` | `0x001c23d8` |
| Classic 24 / 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` | `0x0825dd98` | `0x0817079c` | `0x0818cc58` |
| Classic 33 / 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | `0x082734cc` | `0x08178a3c` | `0x08196590` |
| Classic 35 / 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | `0x08290378` | `0x08190c3c` | `0x081b0374` |
| Classic 38 / 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | `0x08291c5c` | `0x08191500` | `0x081b0cf8` |

The [native recurrence receipt][recurrence-receipt] records image/map identities,
harness hash, native addresses and hashes of all executed instruction spans.
Video 13/20 have identical complete bytes; Video 25 adds exactly 1,536 zero bytes.
Despite that equivalence, all three complete inputs were independently validated,
loaded and executed. Signature matching locates candidates; actual original
instruction execution and asserted results provide the behavioral evidence.

## Daily and weekly event recurrence

Each image independently passed **1,920 candidate-membership checks**, for
**13,440 checks overall**, including exact returned four-word event spans.
The [harness][recurrence-harness] calls native rule constructors, native civil-date
constructors and the complete bounded event membership function. It supplies
synthetic floating same-day event start/end pairs, without timezone objects,
exception lists or additional rule constraints. It does not substitute a Python
recurrence result for a native predicate.

The vectors cover DAILY and WEEKLY, intervals 1 and 2, COUNT 1 and 3, and UNTIL
at the candidate start second or one second earlier. Seeds are Sunday
2026-11-01, Wednesday 2026-11-04, leap crossing 2024-02-28, and year crossing
2026-12-31. Every case queries offsets -2 through +37, preserving 09:00..10:00
in returned spans.

All targets agree on the qualified subset:

- The source seed is included. Event membership rejects candidate days before it.
- DAILY follows interval multiples; WEEKLY retains the source weekday and follows
  multiples of seven times the interval.
- COUNT includes the source occurrence; interval-2 COUNT-3 results are offsets
  0, 2, 4 for DAILY and 0, 14, 28 for WEEKLY.
- UNTIL is inclusive at the exact event-start second. One second earlier excludes
  that candidate. Civil leap/year arithmetic and returned bounds agree.

The rule predicate alone can match a candidate before the seed. The event wrapper
provides the lower bound; the final receipt exercises that wrapper rather than
claiming the standalone rule has the bound. In Video, its original guard is at
`0x0025234c..0x00252364`, branching to the false result at `0x00252450`.

The separate [static bound receipt][static-receipt] records original disassembly
and hashes for each target's COUNT initializer and RRULE constructor. All seven
have a **10,000 candidate-day scan bound** and default UNTIL civil day **1095363**
(3000-01-01), seconds **86400**. Video's loop tests `0x2000 + 0x710` at
`0x0019b464/0x0019b468`. App authoring can use the same conservative last-offset
less-than-10,000 and pre-3000 restrictions already used for Mini 2. COUNT plus
UNTIL remains separately unqualified. Larger interval arithmetic follows the
executed native division/modulo code; this pass directly samples 1 and 2.

## Video saved Calendar reminders

The [Video reminder receipt][reminder-receipt] adds **21 native constructor and
callback cases** plus **21 repeated native trigger-property parsing cases**,
independently across 13/20/25. Existing Classic authoring qualification remains
independently established by the earlier report.

Video constructor `0x00149d84` installs a vtable whose callback slot resolves to
`0x00149cfc`, creates its trigger wrapper through `0x0017d028` and initializes the
trigger pointer to null. The callback compares the actual native token `trigger`
and invokes `0x00149d4c` only for TRIGGER. ACTION:DISPLAY, ACTION:AUDIO, REPEAT
and DURATION return unhandled. Therefore the same conservative trigger-only
single-reminder authoring subset used for Classic is supported here:

```text
BEGIN:VALARM
TRIGGER:-PT15M
END:VALARM
```

The callback/constructor probes explicitly adapt the base parser, allocation,
ASCII key comparison, generic property reader, reference adoption and final
trigger-handler call. Separately executed original trigger parsing confirms
-PT15M becomes a start-relative signed -900 seconds, defaulting to START.
RELATED=END and absolute trigger objects exist, but later scheduling/timezone
semantics remain separate from this safe start-relative writer.

This evidence authorizes a saved reminder representation, not sound selection,
physical delivery, wake behavior or live firmware adoption. Editing existing
eligible reminders must preserve unrelated properties. Ambiguous/multiple,
absolute, end-relative or otherwise unsupported forms retain their original bytes.

## Broader firmware features and limits

The existing exact-image parser reports establish basic events, To Dos,
Calendar containers/names, DTSTART/DTEND, DURATION, RRULE, EXRULE, RDATE, EXDATE,
VTIMEZONE, STANDARD/DAYLIGHT and VALARM construction or dispatch. Video's native
RRULE parser executes DAILY, WEEKLY, MONTHLY and YEARLY construction, plus BYDAY,
BYMONTHDAY and BYMONTH list attachment. Classic has corresponding independently
mapped dispatch and parameter handlers. These are concrete firmware features,
but construction is not an occurrence-level specification for every combination.

This pass does **not** qualify monthly invalid-day handling, yearly leap
anniversaries, BYSETPOS, WKST overrides, exception merging, all-day recurrence,
multi-day recurrence, UTC/TZID transition evaluation or detached occurrence
editing. Basic DATE/UTC/TZID property reads retain their native identity under
the existing app's conservative date model. No Host timezone policy is inferred.
The new recurrence/reminder authoring evidence is **VEVENT-only**; no VTODO
recurrence/reminder write support follows merely from nearby parser tokens.
The firmware has richer native capabilities than this bounded qualification;
these remaining cases must not be mislabeled as firmware absence.

## Nano 3 and Nano 4 recurrence extension

Independent follow-up extends the same event-membership vectors to Nano 3 and
Nano 4: **1,920 checks each**, including exact returned spans and rejection of
pre-seed candidates. These targets do not inherit qualification from Classic
names or API similarity. Nano 3 runs ARM; Nano 4 runs Thumb, with separately
traced constructors, COUNT initialization and event membership.

| Target | OSOS SHA-256 | Event membership | Date constructor | Daily / weekly constructors |
| --- | --- | --- | --- | --- |
| Nano 3 / 1.1.3 | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` | `0x08293ddc` | `0x081ecaf4` | `0x08188228` / `0x081aaefc` |
| Nano 4 / 1.0.4 | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` | `0x08255b2a` | `0x081b2c12` | `0x0816295c` / `0x0817bc54` |

Their receipts record exact maps and executed-span hashes:
[ARM Nano 3](../../.scratch/calendar-nano3-recurrence-native.json) and
[Thumb Nano 4](../../.scratch/calendar-nano4-recurrence-native-v2.json).
Thumb entry addresses in the latter receipt include the instruction-set low bit.
The Nano 4 harness retains the lab's guard against any read or execution of its
uncertain final eight firmware bytes. The native COUNT initializer at
`0x0814bf6c` loads its 10,000 bound from `0x0814bfe8`; the event lower-bound guard
is `0x08255b34..0x08255b42`. The first Nano 4 receipt tested rule predicates only;
**v2** supersedes it for the stronger event-span claim.

Nano 5 is independently covered by the parallel
[Nano investigation](calendar-nano-coverage-2026-11-08.md); its receipt is
[the native recurrence run](../../.scratch/calendar-nano5-recurrence-native.json).

## To Do status-only completion and reopening

A further [native run](../../.scratch/calendar-cross-todo-native.json) executes
**42 constructor and STATUS cases** across the seven Classic/Video inputs.
The native model constructors initialize status at `+0x6c` to zero. The original
STATUS consumers recognize COMPLETED as 2, IN-PROCESS as 3, and CANCELLED as 4.
NEEDS-ACTION and an unknown value leave the initial zero unchanged.

| Target | Model constructor | STATUS consumer |
| --- | --- | --- |
| Video 13/20/25 | `0x00168274` | `0x001dc6a0` |
| Classic 24 | `0x08118b14` | `0x081ae668` |
| Classic 33 | `0x0811e1a8` | `0x081b8138` |
| Classic 35 | `0x08135770` | `0x081d2224` |
| Classic 38 | `0x08135cb4` | `0x081d302c` |

Constructor subobject calls preserve their supplied object pointer, and ASCII
comparison is explicitly adapted. The status stores themselves execute original
instructions. Completing a To Do therefore needs STATUS:COMPLETED; reopening
can remove STATUS to restore the observed native default. This does not qualify
an automatically generated COMPLETED timestamp or percentage-complete field.
Those properties require separate native evidence, and imported bytes remain
preserved until the user explicitly changes the relevant completion state.

## Reproduction

Run from iOpenPod; each harness refuses to overwrite its receipt:

```powershell
uv run --with capstone==5.0.6 --with unicorn==2.1.4 python .scratch/probe_calendar_cross_targets.py
uv run --with capstone==5.0.6 --with unicorn==2.1.4 python .scratch/calendar_cross_static.py
uv run --with unicorn==2.1.4 python .scratch/probe_video_reminder_subset.py
```

The lab's pinned helpers validate originals and supply synthetic RAM/startup
adapters. They remain research dependencies, outside the application runtime.

[recurrence-harness]: ../../.scratch/probe_calendar_cross_targets.py
[recurrence-receipt]: ../../.scratch/calendar-cross-targets-native-v2.json
[static-receipt]: ../../.scratch/calendar-cross-static.json
[reminder-receipt]: ../../.scratch/video-reminder-subset-native.json
