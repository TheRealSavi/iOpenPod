# Calendar timezone and advanced reminder evaluation

Investigated 2026-11-09. Research only; no application behavior or device files
were changed. This continues the [saved reminder qualification](calendar-reminder-qualification-2026-11-08.md)
and [all-model coverage](calendar-firmware-coverage-2026-11-08.md).

## Completed result: all thirteen readable Calendar images

**702 original-instruction evaluation cases** independently qualify relative
START/END anchor choice and signed displacement arithmetic, plus absolute-pair
copying, across the thirteen readable images below. This is later than property
parsing and object construction, but earlier than complete event queries,
scheduler selection, file adoption or physical delivery. No function calls are
substituted in these evaluation runs. Synthetic native objects are supplied as
inputs; their parser and event-query provenance is not assumed.

| Exact image | Original OSOS SHA-256 | Relative evaluator | Absolute evaluator |
| --- | --- | --- | --- |
| 13 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` | `0x1f2340` | `0x1f11f0` |
| 20 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` | `0x1f2340` | `0x1f11f0` |
| 25 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` | `0x1f2340` | `0x1f11f0` |
| 24 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` | `0x81ca5e8` | `0x81c6740` |
| 33 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | `0x81d5d28` | `0x81d1e80` |
| 35 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | `0x81f0014` | `0x81ec0f8` |
| 38 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | `0x81f0ff0` | `0x81ecf20` |
| Mini1FW | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` | `0x73be8` | `0x73bd4` |
| Mini2FW | `346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d` | `0x73f1c` | `0x73f08` |
| Nano1FW | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` | `0x146f24` | `0x145f08` |
| Nano3FW | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` | `0x81f06f4` | `0x81ec84c` |
| Nano4FW | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` | `0x81b59b5` | `0x81b2abd` |
| Nano5FW | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` | `0x8155f9d` | `0x8155eb3` |

Video families 13/20/25 are each latest 1.3; Classic 24/33/35/38 are respectively
1.1.2/2.0.1/2.0.4/2.0.5. Mini 1/2 are 1.4.1, Nano 1 is 1.3.1, Nano 3 is
1.1.3, Nano 4 is 1.0.4 and Nano 5 is 1.0.2. Nano 2 remains encrypted;
Nano 6/7 advertise Calendar synchronization unsupported, as documented in
[the Nano coverage](calendar-nano-coverage-2026-11-08.md). These do not inherit
advanced reminder behavior from the thirteen tested images.

Primary instructions and exact map/span hashes are retained in the independent
[Video/Classic receipt](../../.scratch/calendar-trigger-evaluation-20261109.json)
and [older/Nano receipt](../../.scratch/calendar-trigger-evaluation-older-nano-20261109.json).
The corresponding [Video/Classic harness](../../.scratch/probe_trigger_evaluation_20261109.py)
and [older/Nano harness](../../.scratch/probe_trigger_evaluation_older_nano_20261109.py)
record their own hashes and Unicorn 2.1.4. Earlier receipts remain unchanged.
ARM function signatures are discovery aids; every located body then executes
against its own image and verified runtime map. Thumb addresses retain the
calling-mode bit in the receipt. These private artifacts are research inputs,
not application dependencies.

### Relative evaluation

A mode word of exactly `1` selects the event span's start pair. Modes `0` and
`2` select its end pair. The latter is a diagnostic of the native branch, not a
proposed public third anchor. The selected day/seconds pair is copied and a
signed scalar displacement is added with native day normalization.

Each image runs three spans seeded on 2026-11-01, 2026-12-31 and 2024-02-29,
with start at 00:15 and end the following day at 01:00. For each of the three
mode words, offsets are minus seven days, minus 15 minutes, zero, plus 15
minutes and plus 25 hours. All 45 results per image match the native start/end
selection and civil-day rollover. END-relative triggers therefore have executed
evaluation support, including overnight spans; this does not establish missing
DTEND inference, date-only/multi-day event query semantics or wake delivery.

### Absolute evaluation

The absolute evaluator copies the trigger's stored day/seconds pair to the
result and does not consult the event span, a timezone name, a transition table,
the current clock or a current DST flag. Nine cases per image include seconds
0, 5,400 and the deliberately non-normalized 93,759. Every returned pair equals
its input exactly. The lack of normalization in this leaf is an observation,
not permission to author invalid times.

The earlier Classic construction probes pass floating and uppercase-Z absolute
values as identical civil pairs. Combining that with this copying leaf still
does not prove which timeline the later scheduler assigns to them. An absolute
trigger's own parsed UTC marker must not be treated as proof of UTC scheduling.

## Timezone evidence and its limits

The [Mini 2 native timezone experiments](../../../ipod-firmware-lab/notes/mini2-calendar-alarm-2026-11-06.md#which-timezone-is-used-during-evaluation)
remain the established conversion baseline. Mini 2's event-query converter
`0x00042ba8` selects a zone observance using the device's current DST byte at
`0x1041b6a0`, then applies the selected event-zone offset minus the current device
offset, with direction and civil normalization. A separate parsed-UTC wrapper
`0x000a0b70` selects the supplied zone's standard observance. January/July vectors
therefore must not be interpreted as a verified historical transition engine.

This pass's reminder evaluation does not invoke either conversion path. It
proves no historical TZID resolution, built-in IANA table, DST fold/gap rule,
VTIMEZONE RRULE expansion or full query conversion on the other images. Existing
TZID retention and Calendar-owned zone lookup evidence in
[the original inventory](calendar-alarm-firmware-2026-11-06.md) remains distinct
from those questions. Host timezone rules cannot fill these firmware gaps.

## Multiple reminders: executed single-slot replacement

A separate [native adoption harness](../../.scratch/probe_calendar_reminder_adoption_20261109.py)
and [receipt](../../.scratch/calendar-reminder-adoption-20261109.json) execute
**28 adoption cases** independently across Video 13/20/25 and Classic
24/33/35/38. The native event adoption function, pointer-transfer helper and
trigger-holder validity query execute. Object destruction and free calls are
explicit recording adapters; actual reference-count teardown is not qualified.

For each image, adopting valid holder A stores A at event `+0x30`; adopting valid
holder B replaces it with B. Adopting an empty holder C then clears that slot,
even though a valid holder existed before; adopting A afterward stores A again.
There is no accumulation in this native event slot. This is stronger evidence
than merely observing one pointer in a constructor. It does not prove the full
stream parser adopts every VALARM in source order, and it does not qualify
multiple independent notifications. Mini/Nano adoption was not executed in this
pass and must not inherit this result solely from similar object layouts.

## Full-query provenance

Earlier callback and constructor probes show a single adopted trigger slot;
multiple parsed VALARMs must not be interpreted as multiple independently
scheduled notifications without following adoption and later consumers. The
702 cases above supply one concrete trigger at a time and make no multiple-
reminder claim. Full stream parsing, duplicate adoption and complete scheduling
remain separate experiments.

The native event membership predicate, parsed property converter, full Calendar
query and hardware scheduler are separate stages. In particular, exception and
all-day/multi-day experiments can reveal full-query fallback behavior that a
candidate-membership test does not cover. These trigger leaves cannot validate
an upstream occurrence or zone conversion that was never executed.

## New Mini 1 timezone parity checks

The [Mini 1 harness](../../.scratch/probe_mini1_zones_20261109.py) completes
**six independent native timezone cases** on the exact 1.4.1 image with SHA-256
`2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df`.
The [receipt](../../.scratch/calendar-mini1-timezone-20261109/receipt.json) records
the verified initialized-memory manifest hash, harness hash, each executed
instruction hash and the explicit mock calls. Original image and initialized
block hashes are checked before execution; originals and earlier receipts remain
unchanged.

Actual native zone and observance objects are constructed through `0x000f1260`
and `0x000eac98`; setters `0x000c474c` and `0x000c4754` supply standard minus
18,000 seconds and daylight minus 14,400 seconds, and native collection append
`0x00030eb0` adds them. Native selector `0x0003bc98` returns the corresponding
offset. These synthetic observances intentionally have no DTSTART/RRULE/RDATE
transition rules. Allocation/reallocation/free use explicit Host-memory adapters;
constructor, collection, selection and conversion instructions execute.

The original parsed-UTC wrapper `0x000a083c` maps January 1 and July 1 UTC 01:30
through the supplied zone's standard observance, yielding the prior civil day at
20:30 in both cases. It replaces the UTC marker with the supplied synthetic
zone name. This directly repeats the Mini 2 experiment against Mini 1's own
instructions and memory map.

Original event-query pair converter `0x00042750` uses the current global DST
byte to choose the standard or daylight offset, independently of whether its
input date is in January or July. Four vectors cross both months with both
current DST states and current device offset zero; every native result is noon
minus the selected 18,000 or 14,400 seconds. This converter result is separate
from a complete event query: it does not prove which zone or live context a
query caller supplies, nor any event recurrence or full-query fallback policy.

No additional historical transition/fold/gap resolution is qualified on Nano 1,
Nano 3/4/5, Video or Classic by these Mini results. Their independently executed
relative/absolute reminder evaluation remains valid, while complete timezone
conversion on those images remains an explicit research question.

## Same-day follow-up: parsed transition data on Video, Classic and Nano 1/3

A further **189 native checks on nine images** now extend the current-state
conversion result beyond Mini. Each target constructs its own native Calendar
zone and two observances, appends them through the native collection, and invokes
the original observance property handlers for all three of:

- STANDARD DTSTART `20261101T020000`, RRULE
  `FREQ=YEARLY;BYMONTH=11;BYDAY=1SU`, and RDATE `20251102T020000`.
- DAYLIGHT DTSTART `20260308T020000`, RRULE
  `FREQ=YEARLY;BYMONTH=3;BYDAY=2SU`, and RDATE `20250309T020000`.

The offset-from and offset-to fields of each constructed observance are both set
to its synthetic standard minus 18,000 or daylight minus 14,400 seconds. This is
an explicit experiment input, not a reconstruction of a real jurisdiction's
complete transition definition. Both native RRULE and RDATE fields become
non-null. Native constructors, Gregorian date parsing, rule/list parsing,
collection append, observance selection and conversion execute. The only
adapters are bounded heap allocation, free and a single-thread identifier.

| Exact target | Query pair converter | Current-context words | Parsed UTC wrapper |
| --- | --- | --- | --- |
| 13 | `0x25285c` | `0x10822adc` | `0x18e9a4` |
| 20 | `0x25285c` | `0x10822adc` | `0x18e9a4` |
| 25 | `0x25285c` | `0x10822adc` | `0x18e9a4` |
| 24 | `0x825e2ac` | `0x8948fdc` | `0x81451e8` |
| 33 | `0x82739e0` | `0x89d850c` | `0x814b638` |
| 35 | `0x829088c` | `0x89cfddc` | `0x8162edc` |
| 38 | `0x8292170` | `0x89d8434` | `0x81636a0` |
| 14 | `0x1a609c` | `0x1070b3dc` | `0xeb53c` |
| 26 | `0x82942f0` | `0x8a17944` | `0x815b9d0` |

Targets 13/20/25 are Video, 24/33/35/38 are Classic, 14 is the shared Nano 1
image and 26 is Nano 3. Exact source hashes and memory maps remain those pinned
in the earlier per-image matrix; the new receipts independently record identity
and executed-span hashes:
[seven Video/Classic images](../../.scratch/calendar-zone-cross-transition-20261109-v1.json),
[Nano 1](../../.scratch/calendar-zone-nano1-transition-20261109-v1.json), and
[Nano 3](../../.scratch/calendar-zone-nano3-transition-20261109-v1.json).
Reproducers are [Video/Classic](../../.scratch/probe_zone_cross_transition_20261109.py),
[Nano 1](../../.scratch/probe_zone_nano1_transition_20261109.py), and
[Nano 3](../../.scratch/probe_zone_nano3_transition_20261109.py).
The selected native Video pseudocode used for discovery is retained in
[observance constructors and selector](../../.scratch/calendar-video-observances-20261109.c),
[property dispatcher](../../.scratch/calendar-video-observance-properties-20261109.c),
and [DTSTART/RRULE/RDATE handlers](../../.scratch/calendar-video-observance-rule-handlers-20261109.c).
Those are inferred Ghidra types; executed original bytes take precedence.

For each image, the pair converter receives 2026-01-01, 2026-07-01, 2026-03-08
and 2026-11-01 at 02:30, crossed with current DST states 0 and 1 and current
device offsets 0 and plus 3,600 seconds. All sixteen results use the current DST
flag to choose the standard/daylight observance; the rule's transition date and
input month do not select the offset. Even transition-shaped spring/fall input
pairs follow that branch. This is evidence of current-state dependence, not a
qualified policy for resolving a real nonexistent or ambiguous local time.

Four parsed UTC cases per image, at 01:30 on those same dates, always add the
standard minus-five-hour offset and produce the previous civil day at 20:30.
The live DST flag does not make that wrapper choose the daylight observance.
One further native check per image verifies that a null event-zone pointer makes
both the input query wrapper and the output query wrapper preserve the entire
start/end span unchanged. This establishes the missing-pointer fallback, not how
an unknown TZID becomes missing or whether arbitrary IANA names resolve.

The tested offset selector takes a zone object and an observance-kind flag, with
no event-date argument. It walks observances by kind and reads offset-to; the
queried date enters only the later civil arithmetic. Successfully parsing and
retaining observance RRULE/RDATE content therefore does not establish that this
query-conversion path evaluates those transition rules. Other consumers may do
so and require separate call-graph and native experiments. The complete event
query, Calendar default-zone choice and physical scheduler were not substituted
for this pair-converter result.

## Same-day follow-up: Nano 4 offset-only conversion and Nano 5 bound

Nano 4 / updater 31 / 1.0.4 adds **21 original-instruction checks** using its own
native zone constructor `0x0824e68e`, observance constructor `0x0818d7f8`, and
collection append vtable. The native pair converter is `0x08255e88`, parsed-UTC
wrapper `0x0813f9ec`, input query wrapper `0x08255eb0`, and output query wrapper
`0x08255ee8`. The original image hash and verified runtime-map hash are recorded
in [the new Nano 4 receipt](../../.scratch/calendar-zone-nano4-offsets-20261109-v1.json),
with [the reproducer](../../.scratch/probe_zone_thumb_offsets_20261109.py).
The harness retains the existing guard against the image's unreliable final
eight bytes. Heap and thread-identifier calls are explicit adapters.

This Nano 4 pass constructs offset-only standard/daylight observances. It does
not attach RRULE/RDATE transition objects and must be distinguished from the
nine transition-data targets above. Across the same sixteen date/DST/device-
offset combinations, the native pair converter selects the current DST offset
independently of the input date. Four native UTC parsing/conversion cases always
use the standard offset, and a null-zone input/output wrapper case preserves the
span. Native query direction and civil normalization execute; complete event
query and hardware delivery remain outside the probe.

The initial Nano 5 attempt, superseded by the successful follow-up below, mapped
pair converter `0x081c1b4c`, parsed-UTC wrapper
`0x08226b54`, date-property constructor `0x08226b9c`, input wrapper `0x0819e58c`,
and output wrapper `0x082182b4` are statically mapped from their actual call
sites. A candidate synthetic-zone construction attempt reached an unmapped
write at native `0x08020f0a` before a valid input zone was established. The
candidate constructor was located from a partial code signature; that does not
establish a complete prototype or correct startup context. This is a harness
limitation, not evidence that Nano 5 rejects Calendar zones or lacks timezone
support. The [bounded exploration script](../../.scratch/explore_zone_thumb_offsets_20261109.py)
is retained separately from the successful Nano 4 receipt. No Nano 5 timezone
conversion result is claimed from it. Nano 5's independently qualified reminder
evaluator result earlier in this report remains unchanged.

The follow-up totals **210 new native checks**: 189 on the nine images with
parsed observance DTSTART/RRULE/RDATE inputs, plus 21 Nano 4 offset-only cases.
Mini 1/2 retain their separate established baseline. Nano 5 was still unresolved
at that checkpoint and is closed by the next follow-up. Successful
transition-property parsing is distinct from transition evaluation; these
pair-converter experiments demonstrate current-state dependence in the tested
path without claiming a complete historical VTIMEZONE engine.

## Nano 5 conversion gap closed, 2026-11-10

The successful [Nano 5 harness](../../.scratch/probe_zone_nano5_offsets_20261110_v2.py)
and [21-case receipt](../../.scratch/calendar-zone-nano5-offsets-20261110-v2.json)
construct actual native zones and observances, append them through the native
collection, and execute query conversion, parsed UTC conversion and missing-zone
wrappers. Original raw image SHA-256 remains
`dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49`.
The receipt records the exact IRAM/DRAM map, executed-span hashes, adapter calls
and source hashes; both recorded source files were independently rehashed.

The zone constructor is `0x08114c14` and observance constructor `0x0821cf5e`.
The failed attempt had not disproved their prototypes: it entered an uninitialized
string-storage allocator. The successful probe supplies an explicit backing-store
reallocation adapter at `0x08193b78`, copying the known old allocation's retained
bytes. Native object construction, collection operations, selection and conversion
arithmetic execute; converter results are not substituted.

All sixteen crossed date/DST/device-offset vectors agree with the other targets:
the current DST flag selects the event-zone offset independently of input month
or transition-shaped date. Four parsed UTC cases use the supplied standard
offset; missing event-zone pointers preserve input and output query spans.
These are offset-only observances, like Nano 4's follow-up. Nano 5 does not
inherit the nine other targets' parsed transition-object qualification.

The tested current-state/standard-offset conversion behavior now has native
coverage on all 13 readable Calendar-capable images. This closes the Nano 5
converter gap, not historical transition evaluation, unknown-TZID lookup, fold/gap
policy, full-file default-zone selection or physical scheduling.

## Real Calendar zone lookup and missing-name gate

The new [native lookup harness](../../.scratch/probe_calendar_zone_empty_lookup_20261110_v2.py)
and [receipt](../../.scratch/calendar-zone-empty-lookup-20261110-v2.json)
independently construct Calendar objects and prior-zone objects on Video
13/20/25 and Classic 24/33/35/38. The original Calendar lookup and event gate
execute; the lookup result is not substituted. Heap/free and a fixed Classic
thread identifier remain explicit adapters. Each receipt row binds its original
image and runtime map, located constructors, actual gate-to-lookup call target
and executed-span hashes.

Each native Calendar is freshly constructed. The later populated-lookup work
below corrects the earlier description of an empty collection: the constructor
adds a zone named `Z`. None of the four names in this first probe matches it.
Direct lookup of `America/New_York`, `UTC`, `Missing/Zone` and an empty name
returns zero. For each name, the real event gate is tested twice: with a null
existing zone and with a natively constructed prior zone. All 56 gate vectors
preserve the existing pointer; 28 direct lookups serve as controls.

Video's Calendar constructor is `0x00236d88`, lookup `0x002571fc`, and gate
`0x001dc264`. Classic lookup functions are resolved from each original gate's
actual branch, rather than assuming byte-identical lookup implementations.
The initial Video lookup signature did not locate the Classic implementation;
that discovery mismatch is not evidence of a semantic difference.

This establishes lookup and miss behavior for these fresh Calendar collections.
It is stronger than the earlier gate test with a supplied lookup result, but
does not prove global absence of built-in IANA resolution, populated-name
comparison rules, default-zone selection, or behavior of complete imported
VTIMEZONE components. It also does not imply that a failed lookup resets an
already assigned event zone to UTC: the tested gate explicitly leaves it intact.
Nano/Mini lookup remains separate; the next experiment qualifies populated
collections on these seven images. The old receipt's scope text still calls the
collection empty; that description is superseded here, while its actual tested
names and observed misses remain valid.

## Populated names, built-in Z and duplicate-zone lookup

The [new original-instruction harness](../../.scratch/probe_calendar_populated_zones_20261110_v5.py)
and [seven-image receipt](../../.scratch/calendar-populated-zones-20261110-v5.json)
execute actual Calendar/zone construction, zone insertion, populated lookup and
the event assignment gate independently on Video 13/20/25 and Classic
24/33/35/38. Allocator/free and Classic thread-identifier adapters remain explicit;
no resolver or lookup result is substituted. Each row binds the original image,
runtime map, actual entries and executed-span hashes.

Every fresh native Calendar contains one zone named **`Z`**. A non-intervening
observer records the native constructor helper calling the offset-zone constructor
with that name and offset **zero**. Both `Z` and `z` find the same object;
`UTC` and the empty name miss. Video's default-zone construction helper is
`0x00236b7c`, offset-zone constructor `0x00244c74`, and insertion entry
`0x00236d48`. The corresponding Classic insertion addresses come from the actual
helper's branch, because a longer Video byte signature does not match their
implementation. This does not establish that an event automatically selects `Z`
when DTSTART has no TZID; event default-zone choice is a separate consumer.

The probe inserts three native zones named `Synthetic/Eastern`,
`Synthetic/Western` and `Other/Zone`. Across fifteen lookup keys per image:

- Exact names and the tested ASCII case variants find the corresponding object.
- Leading/trailing spaces, a shortened name, absent names and an unadopted prior
  zone's name miss. The lookup does not discover an object merely because it was
  constructed elsewhere in memory.
- For each key, the actual assignment gate runs with three prior states: null,
  an unadopted native zone, and an already adopted different zone. A hit assigns
  the found pointer; a miss preserves the previous pointer.

That is **105 direct lookup controls and 315 assignment-gate vectors**. The
native Calendar insertion count grows from one to four. Synthetic zone names
qualify matching and assignment; they are not evidence of built-in IANA names,
valid complete VTIMEZONE text or transition evaluation.

### Duplicate identifiers do not have a stable first/last rule

Four further insertions per image retain separate native entries: another exact
`Synthetic/Eastern`, a lowercase `synthetic/eastern`, another `Z`, and lowercase
`z`. The count grows from four to eight, so the tested insertion path does not
deduplicate those names. All seven images produce the same following results.
Here E1 is the original Eastern object, E2 its exact duplicate, E3 the lowercase
duplicate, Z1 the constructor's object, and Z2/Z3 the newly inserted Z/z objects.

| Insertion just performed | Collection count | Eastern lookup, either tested case | Z lookup, either case |
| --- | --- | --- | --- |
| E2 | 5 | E1 | Z1 |
| E3 | 6 | E3 | Z1 |
| Z2 | 7 | E1 | Z2 |
| Z3 | 8 | E1 | Z3 |

In particular, adding Z2 changes the Eastern result even though no new Eastern
object was inserted at that step. This is an observed collection-size/content
dependency; neither universal first-property nor last-property replacement
describes these vectors. The lookup dispatches into the native collection method
recorded in each receipt. Its complete duplicate-selection algorithm and every
insertion permutation are not qualified here. A future integration must not
invent a stable duplicate override policy from the single-name cases.

The [shared source/receipt manifest](../../.scratch/calendar-parameter-and-zone-sources-20261110/manifest.json)
retains the exact reproducer and loader sources and independently checks their
hashes. The old absent-name results remain useful with the corrected fresh-
Calendar description. The complete-stream follow-up now checks populated lookup,
one STANDARD component and event-zone binding on all 13 readable Calendar-capable
inputs. Additional transition consumers and physical scheduling remain open.
[Complete-stream timezone results](calendar-stream-timezone-binding-2026-11-11.md)
