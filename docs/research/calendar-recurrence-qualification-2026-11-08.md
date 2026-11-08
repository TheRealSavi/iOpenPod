# Calendar recurrence: qualified Mini 2 occurrence membership

Investigated 2026-11-08 to distinguish native recurrence parsing from an actual
occurrence evaluator. This extends the
[Calendar/Alarm inventory](calendar-alarm-firmware-2026-11-06.md). The newly
executed target is **Mini 2, updater family 7, RetailOS 1.4.1**. No other target
inherits this qualification from matching field names or nearby code.

## Exact source and experiment

Original OSOS SHA-256:
`346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d`.
The [source manifest][manifest] binds initialized runtime blocks to that image;
each block hash is verified before it is loaded. Manifest SHA-256:
`d8dd483f322ad1513d48c38f3e492e02bb18e50f77a40b7c74aeaa52be6fcc4c`.

The new bounded harness derives its verified image loading, synthetic memory,
allocator mocks and invocation guard from the existing
[Mini Calendar/Alarm probe][base-probe]. That base script SHA-256 is
`cdb81f70742cf2b66a200bfdeaa42787f48a92de62eb55e12743a34f8d607b6b`.
It runs original ARM instructions with Unicorn 2.1.4 and Capstone 5.0.6.
No device, original firmware file or Ghidra project is modified.

Local retained artifacts (ignored, development evidence):

- [Harness][harness], SHA-256
  `7361da309a7e9783b72b77978847d0ecc2d14fb281711e7096982776dab0c95f`.
- [Final receipt][receipt], SHA-256
  `56f6f807744d611469bdb57c6b2bc23f561bd0ae3b7c6ae14bcc509c41afd44b`.

Run from the iOpenPod repository with a previously unused output directory:

```powershell
uv run --script .scratch/probe_mini_recurrence.py --output .scratch/mini-recurrence-native-NEW
```

The receipt retains 720 native event-membership results, shifted start/end pairs,
post-COUNT deadline state, and 42 hashed spans of executed native instructions.
Twelve ordinary configurations query 40 candidate dates each; six additional
weekday/leap/year-boundary configurations query 40 each. Python civil dates
supply input ordinals and assertions; Python does not generate the native result.
Synthetic allocation and zero-initialized event/rule memory are explicit mocks.
This is not complete-file import, native UI, timezone evaluation or physical
reminder delivery.

## Native path exercised

All addresses are runtime ARM addresses, not file offsets.

| Role | Address | Evidence |
| --- | --- | --- |
| Daily rule constructor | `0x00094e20` → `0x000e8cf8` | [Daily factory][daily], [constructor][daily-constructor] |
| Weekly rule constructor | `0x00095514` → `0x000e9f9c` | [Weekly factory][weekly], [constructor][weekly-constructor] |
| Shared rule fields | `0x000e7ac4` | [Base constructor][base-constructor] |
| Native cached date wrapper | `0x000ec5d4` | [Date wrapper][date] |
| Event candidate selection | `0x00053860` | [Event evaluator][event] |
| Rule membership wrapper | `0x0009b050` | [Wrapper][membership] |
| Daily membership | `0x00053b20` | [Daily predicate][daily-predicate] |
| Weekly membership | `0x00053b84` | [Weekly predicate][weekly-predicate] |
| Shared constraints and deadline | `0x00053988` | [Constraint evaluator][constraints] |
| COUNT initialization | `0x000b8834` | [COUNT evaluator][count] |

The event evaluator rejects candidate days before the saved start day, invokes
the actual rule membership wrapper, and returns a shifted event interval. The
predicate is therefore exercised through its event caller, rather than treating
a rule parser's success as proof of an occurrence.

The previously executed native RRULE property parser independently establishes
the mapping of FREQ, INTERVAL, COUNT and UNTIL into these constructor fields.
Its modern constructor defaults INTERVAL to 1, COUNT to 0 and week start to 1.
[Parser constructor][parser-constructor], [earlier parsing evidence][earlier]

## Observed occurrence results

The main seed is November 1, 2026, 09:00–10:00 as an unzoned civil interval.
Offsets are whole days from its start. Every scenario also probes offsets −2 and
−1, which the event caller rejects.

| Rule fields | Matching start offsets through day 37 |
| --- | --- |
| DAILY, interval 1, no COUNT | 0, 1, 2, …, 37 |
| DAILY, interval 2, no COUNT | 0, 2, 4, …, 36 |
| WEEKLY, interval 1, no COUNT | 0, 7, 14, 21, 28, 35 |
| WEEKLY, interval 2, no COUNT | 0, 14, 28 |
| DAILY or WEEKLY, COUNT 1 | 0 only |
| DAILY, interval 2, COUNT 3 | 0, 2, 4 |
| WEEKLY, interval 2, COUNT 3 | 0, 14, 28 |
| DAILY, UNTIL day 14 at 09:00 | 0 through 14, inclusive |
| DAILY, UNTIL day 14 at 08:59:59 | 0 through 13 |
| WEEKLY, UNTIL day 14 at 09:00 | 0, 7, 14 |
| WEEKLY, UNTIL day 14 at 08:59:59 | 0, 7 |

Each returned interval retains the seed's seconds and shifts both day ordinals by
the matching offset. Additional interval-2/COUNT-3 probes use starts November 4,
2026 (Wednesday), February 28, 2024 (leap boundary), and December 31, 2026 (year
boundary), with a 23:00–23:30 interval. Daily matches remain 0/2/4 and weekly
matches 0/14/28. These results establish weekday retention for a simple weekly
rule with no BYDAY selector, without assuming an RFC recurrence engine.

## Bounds and conservative implementation subset

Native daily membership divides the candidate/start day difference by INTERVAL
and tests its remainder. Native weekly membership retains the seed weekday when
there are no overriding selectors, then tests the interval between its week
coordinates. Positive intervals are required for an application interpretation;
zero/negative/overflowed fields are not qualified by these experiments.

The native COUNT initializer scans at most **10,000 candidate days**. It counts
matching days, captures the last matching day/start-second pair as its deadline,
then clears COUNT. Thus an application must not extrapolate an arbitrarily long
COUNT series using generic calendar arithmetic. A conservative simple-rule subset
requires `(COUNT − 1) × INTERVAL < 10000` for DAILY, or
`(COUNT − 1) × INTERVAL × 7 < 10000` for WEEKLY. This restriction follows the
inspected loop; the 10,000-day boundary itself was not natively exhausted here.

The parser's no-UNTIL default is ordinal `0x10b6c3` (January 1, 3000) with seconds
`0x15180` (86,400), **not an infinite sentinel**. A conservative application can
restrict its qualified date range to dates before January 1, 3000. Do not silently
use an unbounded modern recurrence library beyond that firmware deadline.

Recommended initial authoring/expansion qualification is therefore:

- Mini 2 / family 7 / 1.4.1 only, independently selected by Device Registry.
- One modern RRULE on one ordinary VEVENT, DAILY or WEEKLY.
- Positive INTERVAL, optional bounded COUNT **or** floating UNTIL, with the
  native default week start and no BY*/WKST override.
- Floating start/end in the same civil day; returned seconds remain unchanged.
- No TZID, UTC suffix, date-only values, recurrence exceptions, detached
  instances, DURATION, multiple RRULEs or EXRULE/RDATE/EXDATE.
- Unsupported forms retain source bytes and receive an explicit unqualified
  interpretation, rather than being partially expanded.

The test inputs use intervals 1 and 2 and counts 1 and 3. The arithmetic
generalization to other positive intervals within the above bounds additionally
rests on the native predicate and COUNT loop, not on additional native vectors.

## Explicitly unqualified

Combined COUNT and UNTIL was attempted in a separate preliminary run. A stricter
UNTIL left native COUNT initialization scanning until the harness's 750,000
instruction bound; no completed result was recorded. Keep the combination
unsupported rather than asserting RFC precedence or an infinite loop.

MONTHLY/YEARLY construction is known from earlier work, but no new occurrence
semantics were qualified here. Invalid month days, leap anniversaries, BYDAY,
BYSETPOS, week-start overrides, exceptions, timezone/DST transitions, all-day and
multi-day behavior remain separate investigations. The Mini event query's
exclusive overlap matcher was established previously, but the present tests do
not qualify the complete query range scheduler or reminder timing.

Video 5/5.5 and Classic 24/33/35/38 retain their prior parser-only recurrence
evidence. None gains occurrence expansion from this Mini result.

[manifest]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/manifest.json
[base-probe]: ../../../ipod-firmware-lab/scripts/check_mini2_calendar_alarm.py
[harness]: ../../.scratch/probe_mini_recurrence.py
[receipt]: ../../.scratch/mini-recurrence-native-20261108-v5/receipt.json
[earlier]: ../../../ipod-firmware-lab/notes/mini2-calendar-alarm-2026-11-06.md
[daily]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00094e20.c
[weekly]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00095514.c
[daily-constructor]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000e8cf8.c
[weekly-constructor]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000e9f9c.c
[base-constructor]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000e7ac4.c
[date]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000ec5d4.c
[event]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00053860.c
[membership]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/0009b050.asm.txt
[daily-predicate]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00053b20.c
[weekly-predicate]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00053b84.c
[constraints]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00053988.asm.txt
[count]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000b8834.c
[parser-constructor]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/000ec6ac.c
