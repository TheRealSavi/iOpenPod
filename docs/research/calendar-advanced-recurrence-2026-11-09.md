# Advanced Calendar recurrence investigation

Investigated 2026-11-09 against original RetailOS images. This is research only;
no application behavior or device files were changed. It extends the
[existing cross-model qualification](calendar-classic-video-coverage-2026-11-08.md)
and [legacy qualification](calendar-legacy-coverage-2026-11-08.md).

## Qualification-stage correction

The initial property-only YEARLY results below are **pre-finalization diagnostics**.
The 2026-11-09 follow-up executes the original VEVENT RRULE adoption handler and
event recurrence finalizer. On all three Video images, bare YEARLY COUNT=3 from
2024-02-29 then selects **2024-02-29, 2028-02-29 and 2032-02-29**, skipping
non-leap years. The earlier consecutive-day output must not be used as the
firmware's final event behavior. The retained old receipts document why the
finalization stage is required; they are not final occurrence specifications.
See [the finalized native receipt](../../.scratch/calendar-yearly-event-finalization-v2-20261109.json).
Cross-model finalization checks are being completed separately.

## Evidence levels and exact inputs

The [Video parsed-rule receipt][video] executes original RRULE property
construction/parsing at `0x001f2218`, getter/factory at `0x001f21f0`, civil-date
construction at `0x001f1498`, and event membership at `0x00252340`. It submits
complete RRULE text through the native parameter/value parser, not a hand-built
constraint object. The native firmware startup copy/zero routine runs first.
Heap allocation is adapted; rule parsing and predicates are original ARM code.
The event's floating same-day start/end pairs are synthetic. This is not a whole
VCALENDAR stream or a physical-device observation. Component-level context and
late default injection must be checked separately before broader file claims.

All three latest Video inputs were independently loaded and executed:

| Updater / RetailOS | Original plaintext OSOS SHA-256 |
| --- | --- |
| 13 / 1.3 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| 20 / 1.3 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` |
| 25 / 1.3 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` |

The receipts retain harness hashes, startup provenance and every executed
instruction span's hash. All successful membership results additionally assert
exact 09:00..10:00 returned spans; no Host timezone enters the experiment.

## Completed parsed-rule results on Video 13/20/25

All three images return the same observed results. COUNT includes matching
candidates and does not force an otherwise filtered source date into the result.

| Rule and source | Native returned dates in the queried window |
| --- | --- |
| MONTHLY;COUNT=4, source 2026-01-31 | Jan 31, Mar 31, May 31, Jul 31 |
| MONTHLY;COUNT=4, source 2026-01-30 | Jan 30, Mar 30, Apr 30, May 30 |
| MONTHLY;INTERVAL=2;COUNT=4, source Jan 31 | Jan 31, Mar 31, May 31, Jul 31 |
| MONTHLY;BYMONTHDAY=-1;COUNT=4, source Jan 1 | Jan 31, Feb 28, Mar 31, Apr 30 |
| MONTHLY;BYDAY=MO;COUNT=5, source Jan 1 | Jan 5, 12, 19, 26, Feb 2 |
| MONTHLY;BYDAY=1MO;COUNT=4, source Jan 1 | Jan 5, Feb 2, Mar 2, Apr 6 |
| MONTHLY;BYDAY=-1FR;COUNT=4, source Jan 1 | Jan 30, Feb 27, Mar 27, Apr 24 |
| DAILY;BYDAY=MO;COUNT=3, source Nov 1 | Nov 2, 9, 16 |
| WEEKLY;BYDAY=MO,WE;COUNT=6, source Nov 4 | Nov 4, 9, 11, 16, 18, 23 |

Bare MONTHLY skips months lacking the seed day. There is no clamping of January
31 to February's last day in the tested cases. Explicit negative BYMONTHDAY
instead selects a position from the end of each actual month.

### WKST changes interval-week membership

For source Sunday 2026-11-01 and
`FREQ=WEEKLY;INTERVAL=2;BYDAY=SU,MO;COUNT=6`:

| WKST | Native results |
| --- | --- |
| MO | Nov 1, 9, 15, 23, 29, Dec 7 |
| SU | Nov 1, 2, 15, 16, 29, 30 |

A Wednesday source with MO,WE does not distinguish the two week starts in the
sampled interval. A shared weekday implementation must therefore not treat a
single non-distinguishing vector as proof that WKST is ignored.

### Pre-finalization YEARLY diagnostic, superseded for final event behavior

`FREQ=YEARLY;COUNT=3` with source 2024-02-29 yields **2024-02-29, 2024-03-01,
2024-03-02**, not annual leap-day anniversaries. This result includes native
RRULE parsing and the event membership wrapper. The rule constructor alone is
not being substituted for the parser. It remains a property-level experiment;
any whole-component finalization/default injection is a separate path.
The later event-finalization follow-up supersedes this diagnostic for final
event behavior: source-month/day defaults are established after property parsing.

The higher-budget [follow-up receipt][video-followup] demonstrates that explicit
`FREQ=YEARLY;BYMONTH=11;BYMONTHDAY=1` without COUNT selects Nov 1 in 2026, 2027
and 2028. Explicit fields therefore differ materially from the bare form.

### BYSETPOS and bounded incomplete COUNT cases

The first sweep bounds each event-membership call at **1,000,000 original
instructions**. Four sparse or positional COUNT cases reach this limit while
initializing their candidate search: last weekday of a month, yearly Nov 1,
yearly last February day, and daily BYHOUR with BYSETPOS. These are incomplete
observations, not claims that firmware rejects the rules or contains a loop bug.
The receipt records the candidate offset and stop PC for each incomplete case.

A separate run raises the per-call bound to **20,000,000 instructions** and adds
no-COUNT controls. Without COUNT, MONTHLY with BYDAY=MO,TU,WE,TH,FR and
BYSETPOS=-1 selects Jan 30, Feb 27, Mar 31, Apr 30 and May 29 of 2026. This
qualifies the tested positional predicate separately from sparse COUNT setup.
At this higher bound, the last-weekday COUNT=4 case completes with Jan 30,
Feb 27, Mar 31 and Apr 30. Explicit yearly Nov 1 COUNT=3 and last-February-day
COUNT=3 also complete; the latter yields Feb 29 in 2024 and Feb 28 in 2025/2026.
Only the DAILY;BYHOUR=9,17;BYSETPOS=-1;COUNT=3 vector remains incomplete at
20 million instructions. No after-bound result is claimed. These higher-budget
controls execute Video 13 only; their exact-byte common code with 20/25 is
supporting equivalence, not an independently completed high-budget run there.

## Cross-model constructor-level findings

A separate sweep runs native MONTHLY/YEARLY constructors and full event
membership on Classic 24/33/35/38, Video 13/20/25, Nano 3/4/5, Mini 1/2 and Nano 1.
These experiments use synthetic rule fields directly and therefore do not prove
identical parser-default behavior on every target. Their input hashes/maps follow
the independently validated original-image loaders used by the earlier reports.
Receipts additionally record the exact current constructors and executed spans.

The ten modern inputs independently complete **60 scenarios / 9,260 native
event-membership queries** with no bounded failures. Their direct-constructor
results agree, including monthly invalid-day skipping and the bare yearly
filter behavior. The [cross-target receipt][cross] retains per-image identities,
constructors, date/event addresses, scenario inputs and executed-span hashes.

### Legacy raw-constructor discrepancy resolved through native parsing

The initial Mini 1/2 and Nano 1 direct-constructor probes returned consecutive
matching days for bare MONTHLY, whereas modern probes retained the source day.
That observation **does not establish a model compatibility difference**. The
subsequent native RRULE parsing probes close the distinction: all three legacy
parsers return the same monthly source-day pattern as Video, including invalid
months skipped and interval 2 preserved. The direct constructors had omitted
parser-established state/defaults. This is why a raw object result cannot stand
in for imported property semantics.

| Target | Native RRULE constructor | Native getter/factory | Parsed monthly result, Jan 31 COUNT=4 |
| --- | --- | --- | --- |
| Mini 1 | `0x000ec54c` | `0x000a0924` | Jan 31, Mar 31, May 31, Jul 31 |
| Mini 2 | `0x000ec6ac` | `0x000a0c58` | Jan 31, Mar 31, May 31, Jul 31 |
| Nano 1 | `0x00146dfc` | `0x00146dd4` | Jan 31, Mar 31, May 31, Jul 31 |

Each legacy parsed-rule run executes **five scenarios / 910 event-membership
queries** with exact spans: January 31, January 30, interval 2, February 29,
and bare YEARLY COUNT=3. The latter still yields Feb 29, Mar 1, Mar 2, agreeing
with the parsed Video property result. No additional whole-file context is
implied by these property-level parser probes.

Legacy parsed receipts: [Mini 1][mini1-parsed], [Mini 2][mini2-parsed],
[Nano 1][nano1-parsed]. The earlier raw-constructor receipts are kept separately
for audit: [Mini 1][mini1], [Mini 2][mini2], [Nano 1][nano1]. All original image
and map hashes are bound in those receipts; no equivalence relies on model names.

No cross-model difference is demonstrated for the completed, comparable monthly
vectors. YEARLY conclusions require the finalized-stage qualification below.
The later parsed BY*/WKST sweep extends beyond the original Video-only evidence;
the earlier direct constructors alone did not establish that coverage.

## Reconciled follow-up, 2026-11-10

### Parsed BY*, positional and week-start vectors

Twelve parsed-rule vectors now complete on Mini 1/2, Nano 1/3/4/5, and all
Classic builds, matching the original Video vectors. They cover negative
BYMONTHDAY, monthly weekday filters and ordinal weekdays, weekly multiple
weekdays with distinguishing WKST inputs, daily weekday filtering, last weekday
BYSETPOS without COUNT, and explicit yearly month/day constraints. This is a
finite tested subset, not every combination of BY* properties.

Receipts: [Video](../../.scratch/calendar-advanced-followup-video-20261110.json),
[five ARM targets](../../.scratch/calendar-advanced-followup-arm-20261109.json),
[Mini 1](../../.scratch/calendar-advanced-followup-mini1-20261109/receipt.json),
[Mini 2](../../.scratch/calendar-advanced-followup-mini2-20261109/receipt.json),
[Nano 1](../../.scratch/calendar-advanced-followup-nano1-20261109/receipt.json),
[Nano 4](../../.scratch/calendar-advanced-followup-nano4-20261110.json), and
[Nano 5](../../.scratch/calendar-advanced-followup-nano5-20261110-v5.json).
All twelve Nano 5 result sets were independently compared with Nano 4 and the
other eight follow-up inputs; they agree and contain no bounded failures.

Nano 5's earlier parser attempts failed in an uninitialized allocator path.
The successful [new harness](../../.scratch/probe_advanced_followup_nano5_20261110_v5.py)
adapts string allocation/reallocation/free at `0x081935bc`, `0x08193b78` and
`0x0819af00`, plus C++ allocation/free and a fixed thread identifier. A recorded
TLB-invalidation instruction is skipped in the emulator's flat map. Original
RRULE parsing, rule construction and event membership execute. This is not OS
pool initialization or a complete-file acceptance test. Exact adapter addresses,
original image/runtime map and source hashes are retained in the new receipt;
the failed attempts remain diagnostic artifacts, not unsupported-feature evidence.

### Finalized YEARLY semantics supersede the rule-only diagnostic

The native event finalizer establishes missing rule defaults after property
parsing. With source 2024-02-29 and bare `FREQ=YEARLY;COUNT=3`, finalized events
match **2024-02-29, 2028-02-29 and 2032-02-29**, skipping non-leap years.
The earlier consecutive-day predicate result is pre-finalization and must not
be used as the semantics of a completed imported event.

This stage is independently executed on all thirteen readable Calendar-capable
images: Video 13/20/25, Classic 24/33/35/38, Nano 1/3/4/5, Mini 1 and Mini 2.
Receipts are
[Video event adoption/finalization](../../.scratch/calendar-yearly-event-finalization-v2-20261109.json),
[Classic and Nano 3](../../.scratch/calendar-yearly-finalized-arm-20261109.json),
[Mini 1](../../.scratch/calendar-yearly-finalized-mini1-20261110/receipt.json), and
[Mini 2](../../.scratch/calendar-yearly-finalized-mini2-20261110/receipt.json), and
[Nano 1](../../.scratch/calendar-yearly-finalized-nano1-20261110/receipt.json),
[Nano 4](../../.scratch/calendar-yearly-finalized-nano4-20261110-v2.json), and
[Nano 5](../../.scratch/calendar-yearly-finalized-nano5-20261110-v2.json).
The Mini finalizers are `0x0006368c` and `0x000639d8`; the Video finalizer is
`0x00167f90`. Source spans and actual candidate results are checked after native
finalization. Nano 1's finalizer `0x000c617c` was located by normalized original
instruction matching, then executed on its independently pinned image with
asserted returned spans. The Nano 4/5 finalizers `0x0811f9f8` and `0x081e1f18`
were separately located from original Thumb instructions: both construct the
native source date, invoke rule finalization through vtable slot `+0x0c`, and
also finalize an exclusion rule when present. The subsequent native runs assert
the same three anniversaries and exact spans. All fourteen sampled candidate
offsets per image include non-anniversary and post-COUNT controls. The finite
Thumb per-call bound is 20 million instructions. No whole filesystem import is claimed.

### The bounded daily positional case is a finite zero-match scan

The [post-finalization diagnostic](../../.scratch/calendar-daily-positions-finalized-diagnostic-20261109.json)
repeats the problematic Video-13 DAILY/BYHOUR/BYSETPOS vector after native event
finalization. The daily period getter `0x001abb0c` produces equal day bounds;
the positional iterator `0x001bc194` uses an exclusive upper bound, producing
no positional candidates in the tested path. Without BYSETPOS, the BYHOUR
control matches the seed-time event on successive days; adding BYSETPOS=-1
without COUNT gives no candidates.

With COUNT=3, initialization advances days without decrementing the requested
count. The diagnostic stops deliberately after 32 completed candidate evaluations
(the 33rd entry), at 86,465 original instructions. Together with the separately
verified 10,000-day native cap, this explains why a 20-million-instruction budget
can expire before the finite search ends. It does not establish an infinite loop
or a device hang. This detailed diagnostic is Video-13-only and does not grant
authoring rights for the shape on other targets.

## Implementation implications

Ready-to-specify candidates from the completed parsed-rule vectors include
monthly seed-day repetition with invalid months skipped, positive/negative
BYMONTHDAY, explicit monthly ordinal weekdays, and multiple weekly weekdays with
an explicit WKST. The shared vector sets now cover all thirteen images; they do
not qualify arbitrary compound rules or whole-file defaulting. YEARLY requires native event
finalization after parsing; all thirteen images now have finalized leap-day checks.
Sparse/positional COUNT initialization needs per-image
bounds work despite the successful higher-budget Video-13 controls. Recurrence
exceptions, timezone transition evaluation and VTODO evaluation are separate
investigations. No support is inferred merely from a token or constructor.

[video]: ../../.scratch/calendar-advanced-video-20261109.json
[video-followup]: ../../.scratch/calendar-advanced-video-budget20m-20261109.json
[cross]: ../../.scratch/calendar-advanced-cross-v2-20261109.json
[mini1]: ../../.scratch/calendar-advanced-mini1-20261109/receipt.json
[mini2]: ../../.scratch/calendar-advanced-mini2-20261109/receipt.json
[nano1]: ../../.scratch/calendar-advanced-nano1-20261109/receipt.json
[mini1-parsed]: ../../.scratch/calendar-advanced-mini1-parsed-20261109/receipt.json
[mini2-parsed]: ../../.scratch/calendar-advanced-mini2-parsed-20261109/receipt.json
[nano1-parsed]: ../../.scratch/calendar-advanced-nano1-parsed-20261109/receipt.json
