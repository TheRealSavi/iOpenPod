# Native Calendar exceptions and event spans

Investigated 2026-11-09. This is research only: no app behavior, firmware, or
physical device was changed. Results below distinguish original native candidate
membership from the actual event-query wrapper. That distinction changes the
meaning of excluding the initial event.

## Exact initial targets and evidence

| Target / updater / release | Original OSOS SHA-256 | Corpus manifest SHA-256 |
| --- | --- | --- |
| Mini 1 / 3 and 6 / 1.4.1 | `2f844307acf62702fc247b19a148f35d497ce59d6ef7790b242200b5d64b09df` | `d32cca7a0c7f5109b1d2a9287b0d3988f131f111e1e17370fb67331d61bcbd7b` |
| Mini 2 / 7 / 1.4.1 | `346504450c5201a632cafa38312093fc04b402b4ca37c79d7ca4a4167bb8f34d` | `d8dd483f322ad1513d48c38f3e492e02bb18e50f77a40b7c74aeaa52be6fcc4c` |
| Nano 1 / 14 and 17 / 1.3.1 | `2d34721c1d36f592b076ca111822cea6afcf718331dcf4117618f0eb338bf4cb` | `9fd79ed06dbf964e35261cbf8b74ed3b6ca9785970404fe7cdb199eab859e687` |

The independently reconstructed maps and updater aliases are documented in the
[legacy coverage report][legacy]. Every harness verifies the original image and
initialized mapped-memory hashes. Fresh processes isolate each fixture because
a native collection comparator caches an allocated singleton; resetting a mocked
heap while retaining that singleton is invalid. A preliminary multi-fixture
single-process attempt failed for this reason and produced no success receipt.

| Target | Date-list property / result extraction | Candidate membership | Full event query |
| --- | --- | --- | --- |
| Mini 1 | `0xec86c` / `0xa0970` | `0x53514` | `0x9a918` |
| Mini 2 | `0xec9cc` / `0xa0ca4` | `0x53860` | `0x9ac4c` |
| Nano 1 | `0x14ed1c` / `0x14ecf0` | `0x1a5b80` | `0x1a5d08` |

Native date-list properties construct real native collections. Real DAILY/WEEKLY
constructors supply inclusion/exclusion rules. The fixture explicitly installs
those objects into independently identified model slots; this is not a complete
stream importer test. The allocator is the only reachable substituted operation
in these evaluation paths. Timezone conversion is bypassed by the native null
zone pointer, not replaced by Host timezone rules.

## Candidate membership and full query differ

For a same-day 09:00–10:00 source event on 2026-11-01:

- A weekly rule plus RDATE November 3 matches November 1, 3, 8 and 15.
- A daily rule minus EXDATE November 3 omits November 3.
- If RDATE and EXDATE both include November 3, exclusion wins for that candidate.
- A daily inclusion rule minus a weekly EXRULE omits candidate offsets 0, 7, 14.
- A pre-seed RDATE is rejected by the native candidate guard.

These observations alone do **not** define the final user-visible query result.
The [Mini 2 full query][mini-query] first requests recurrence matches. If no
match survives, it tests overlap with the original saved source span and returns
that original span when it overlaps. The [Nano 1 query][nano-query] independently
has the same branch structure. Executed seed-exclusion cases confirm it on
Mini 1, Mini 2 and Nano 1.

Consequences: EXDATE November 1 or the weekly EXRULE can remove the seed from
candidate membership, but the actual day query still returns the original
November 1 span. Likewise, a document with only RDATE November 3 returns its
saved November 1 source event as well as the added November 3 occurrence.
Pre-seed RDATE does not add an earlier occurrence. A generic RFC set expression
that removes the initial event would disagree with this observed wrapper.

The [candidate matcher][mini-member] combines source-span membership or an
inclusion rule/date, then excludes matching exclusion rules/dates. It checks
only dates for the tested RDATE/EXDATE collections: RDATE November 3 at 15:00
still returns the shifted source 09:00–10:00 event. Date-only November 3 values
also work on this path. This does not qualify RDATE periods, zoned forms or a
separate time for an added occurrence.

## Date-list separator is a native parser input

The tested zero-flag event route obtains separator `0x3b` from
[the original separator selector][separator] when both saved legacy flags are
zero. The version-specific follow-up below now establishes that this is the
Mini 2 VERSION:2.0 route. The date-list fixture uses that actual separator. Under that framing,
`20261103T090000;20261105T090000` adds both dates, while a comma-separated value
adds only the first date in these property-level tests. Duplicate semicolon dates
do not create duplicate results in this query API, which returns one span.

This must be retained as a framing-specific parser observation. It does not
justify silently normalizing imported comma lists or asserting complete document
lexer behavior from the property constructor alone. Multiple repeated properties,
complete root-stream lexical treatment and mixed value parameters remain separate
tests; the follow-up qualifies a narrower event-body stream boundary.

## All-day and multiday source spans

The same native query/evaluation path accepts a source pair at midnight
November 1 through midnight November 2. Weekly recurrence plus RDATE November 3
returns the exclusive one-day spans November 1–2, 3–4, 8–9 and 15–16. Equal
endpoints do not overlap: the [native interval matcher][overlap] uses strict
start-before-end comparisons. This is evaluation of the existing civil-day span;
it does not qualify omitted DTEND defaults or every DATE-property parse route.

Multiday events need more care than preserving duration. A source November 1
23:00 through November 3 01:00 spans 26 hours. The candidate matcher accepts
candidate dates inside that original source-day extent before consulting the
RRULE. As a result a weekly series can include a shifted November 2 23:00 through
November 4 01:00 span in this query path, even though November 2 is not on the
weekly interval. The native query searches candidates around each requested day
using the source day extent and returns the first overlapping accepted span.
It can therefore return different spans from a generic recurrence engine.

For a daily series, excluding a start date does not remove overlap from an
already-started earlier occurrence. EXDATE November 3 omits that candidate, but
November 3's day query can still return an earlier 26-hour span. The source-span
fallback remains in force when no recurring candidate survives.

A no-rule control takes the source-span overlap branch directly, rather than
materializing extra shifted source dates. This control prevents interpreting the
candidate helper as the public query contract.

## Detached exceptions

The actual entry callbacks independently return unhandled for `UID` and
`RECURRENCE-ID` on all three initial targets, with no property consumer called:
Mini 1 `0x52c00`, Mini 2 `0x52f4c`, and Nano 1 `0x12f124`. The native comparison
routine executes unchanged; generic parser reading/final consumers are hooked
only for observation, and neither is reached by these unknown-property cases.

This supports **no detached UID/RECURRENCE-ID merger in these tested callbacks**.
It does not prove absence of every other model/collection route. The application
must retain detached components without inventing a merger from RFC assumptions.
Receipts are `.scratch/{Mini1FW,Mini2FW,Nano1FW}-detached-exception-dispatch-20261109-v1/receipt.json`.

## Reproduction and implementation consequences

Private source harnesses are
`.scratch/probe_{mini1,mini2,nano1}_exceptions_fullquery.py`. Each case has a new
process and output directory. The v3 receipts preserve a copy of the exact
harness, its SHA-256, original image and map hashes, executed instruction-word
hashes, input shape, candidate results and actual query spans. Older preliminary
receipts are retained without overwriting them.

The completed legacy sweep has 16 fixture patterns across timed, one-day
midnight and 26-hour source spans. Every fixture checks 19 candidate dates and
19 actual day queries against explicit span/set assertions: **144 fixtures and
5,472 native candidate/query checks**, all passed. Receipts live under
`.scratch/{mini1,mini2,nano1}-exceptions-query-20261109-*-*-v3/receipt.json`.
The [receipt index][index] binds all 144 receipt hashes. Six additional actual
UID/RECURRENCE-ID callback checks passed across these three original images.

## Later-family query and span extension

A separate independently mapped sweep exercises the actual query wrapper and
candidate predicates for three Video images, four Classic images, and Nano 3/4/5.
Each target passes 12 fixtures: no rule, daily, weekly, and daily minus weekly
EXRULE, each with timed, one-day midnight and 26-hour spans. At 19 candidates
and 19 actual queries per fixture, this adds **4,560 native checks**, all passed.
The shared source-span fallback, EXRULE seed-restoration and multiday first-span
behavior match the legacy fixtures on these tested inputs.

| Updater | Original plaintext source SHA-256 | Actual query entry |
| --- | --- | --- |
| 13 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` | `0x2524c8` |
| 20 | `f7b7670bafd1d6ac45effa00b4d314550c030218a953468cfc6057d6d80e6ea7` | `0x2524c8` |
| 25 | `784ae3d5540fd2f89e8c947b93629e97f62a06dc311d9745aab143e4db6bb251` | `0x2524c8` |
| 24 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` | `0x825df18` |
| 33 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` | `0x827364c` |
| 35 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` | `0x82904f8` |
| 38 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` | `0x8291ddc` |
| 26 | `ff5980009c6720742f5b85f3e80a5c853bd0e3caa433d015e6836c209e08081a` | `0x8293f5c` |
| 31 | `a5d273ab3be00dcea90e72444bb9750ebe5d88f5f986c3e62e4fd108332ff372` | `0x8255c05` |
| 34 | `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49` | `0x826ac05` |

The [cross-family receipt][cross] records exact image identity, constructors,
member/query addresses, original memory-map identities, full query spans and
executed-span hashes. Thumb entry addresses include the instruction-set bit.
Video executes its original startup copy/zero routine at `0x83848` before the
probe; its map is therefore reconstructed by native execution. Nano 5's receipt
records its exact IRAM/DRAM source-offset mapping. Classic/Nano 3/4 receipts bind
their independent memory-map hashes. The private
`.scratch/calendar-exceptions-spans-cross-20261109-sources/manifest.json` additionally
binds retained copies of all mapper/harness sources and the cross-family receipt.
No substituted operation is reached by these direct rule/date constructors and
query calls; the Video adapter's allocator hooks are not reached in this sweep.

Combined evaluation coverage is **10,032 native checks** across all 13 readable
Calendar images, plus the six initial detached-exception dispatch checks.
The follow-ups below extend callback routing and independently qualify Mini 2
version framing. The final later-family section additionally executes list-value
parsing and merging with explicit entry flags; callback routing alone did not
supply those semantics.
Nano 2's encrypted image cannot be evaluated here;
Nano 6/7 lack the qualified native mounted-file Calendar workflow and are outside
this Calendar evaluation set.

## Version framing and later-family dispatch, 2026-11-10

The [seven-target ARM dispatcher receipt](../../.scratch/calendar-arm-exception-dispatch-20261110.json)
independently executes original callbacks on Video 13/20/25 and Classic
24/33/35/38. Each handles RDATE, EXDATE and EXRULE, with SUMMARY as a control,
and returns unhandled for UID, RECURRENCE-ID and an unknown property. Native
key comparisons and selected downstream handlers are explicit adapters; no
date-list evaluation or complete-file acceptance follows from these 49 cases.

The [Nano dispatcher receipt](../../.scratch/calendar-nano-exception-dispatch-20261109-v1.json)
also contains independently executed entry routing for Nano 3/4/5: RDATE,
EXDATE and EXRULE are handled, UID and RECURRENCE-ID are not. It additionally
contains other Calendar/To Do/reminder routing cases. Together with the earlier
legacy probes, the tested entry callbacks on all 13 images ignore the detached
identity properties. This is not proof that every possible collection or import
route lacks a detached merger, nor permission to invent one in iOpenPod.

### Mini 2 root version flag through event-body parsing

Four [native framing runs](../../.scratch/probe_mini2_version_frame_20261110.py)
execute original root constructor `0x000e759c`, VERSION consumer `0x00081f1c`,
event-child constructor `0x000ebd24`/`0x000eb820`, generic event-body parser
`0x00053db8` and actual event query `0x0009ac4c`. The root's compared token is
the literal **1.0**, verified from original bytes. It sets root byte `+0x84` to
one only for VERSION:1.0; that byte reaches child parser `+0x80`.

| VERSION input | Child flag | RDATE list separator | Query matches, offsets from source day |
| --- | --- | --- | --- |
| 2.0 | 0 | Semicolon | 0, 2, 4 |
| 2.0 | 0 | Comma | 0, 2 |
| 1.0 | 1 | Comma | 0, 2, 4 |
| 1.0 | 1 | Semicolon | 0, 2 |

Receipts:
[2.0 semicolon](../../.scratch/mini2-version2-semicolon-20261110/receipt.json),
[2.0 comma](../../.scratch/mini2-version2-comma-20261110/receipt.json),
[1.0 comma](../../.scratch/mini2-version1-comma-20261110/receipt.json), and
[1.0 semicolon](../../.scratch/mini2-version1-semicolon-20261110/receipt.json).
Each binds the original image, initialized-memory manifest, harness hash and
executed instruction words. An ASCII character-source adapter supplies the
event body, including RDATE and END:VEVENT; native lexical treatment and list
construction then execute. The VERSION value is supplied to its real handler,
not inferred from a zero-filled parser. A complete root text stream, encodings,
filesystem opening and mounted-device adoption remain outside this boundary.

Thus the earlier zero-flag semicolon observation survives this narrower native
VERSION:2.0 framing experiment. It still must not be generalized to every model,
silently normalized into imported bytes, or confused with a standard-format
requirement. At that checkpoint, repeated-property full-stream parsing, mixed
VALUE/TZID parameters and later-model root-to-child flag transfer remained
follow-up work. The later sections close the first two at their tested boundaries.
The subsequent complete-stream matrices also verify VERSION transfer and list
behavior on all 13 readable inputs. [Firmware coverage matrix](calendar-firmware-coverage-2026-11-08.md)

### Repeated-property follow-up and stream-adapter audit

Four additional Mini 2 cases execute the actual RDATE handler `0x0007f658`,
EXDATE handler `0x00079038`, native list constructors, merge functions
`0x00031068`/`0x00030fc0`, and full event query. They retain the original root
VERSION handler and child construction, but bypass the character-stream adapter.
The [validation index](../../.scratch/mini2-direct-validation-20261110.json)
binds all four receipts and independently verifies their saved harness hashes.

| Property sequence | Native query matches, source-relative days |
| --- | --- |
| RDATE day 2, then RDATE day 4 | 0, 2, 4 |
| RDATE day 4, then RDATE day 2 | 0, 2, 4 |
| RDATE days 2/4, then separate EXDATE day 2 and EXDATE day 4 | 0 |
| RDATE day 2, then empty RDATE | 0, 2 |

The native setters merge date collections. Repeated RDATE and EXDATE properties
do not follow a first-property or last-property replacement policy in these
adoption paths. The empty added-date collection leaves the earlier dates intact.
This qualifies handler/adoption/query semantics; root text parsing, VALUE/TZID
metadata and filesystem acceptance are separate boundaries.

An observational 12-fixture extension of the earlier ASCII-source adapter exposed
a limitation: some later properties never reached their native callbacks. Its
apparent first-property-only results therefore are **not firmware semantics**.
In particular, an uninvoked EXDATE handler is not evidence that firmware ignores
EXDATE. The retained
[observational harness](../../.scratch/probe_mini2_repeated_stream_20261110.py)
and [input fixtures](../../.scratch/calendar-stream-fixtures-20261110.json)
are diagnostic artifacts. The single-property VERSION/separator experiments
remain their explicitly narrower boundary; they do not validate this adapter
for multi-property streams. The successful direct native tests above prevent
promoting the adapter failure into a compatibility rule. The source-interface
correction and successful complete-root experiments are recorded below.

No Calendar feature receives new application edit rights from this report alone.
An implementation must model the native query fallback, date-only exception
matching, framing-dependent list parser and multiday candidate behavior explicitly.
A generic RFC expansion, detached-exception merger or imported-value rewrite would
exceed the evidence. UTC/TZID, DST, invalid spans, missing-end defaults, combined
advanced rules and physical firmware adoption remain unresolved by this pass.

[legacy]: calendar-legacy-coverage-2026-11-08.md
[mini-query]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/0009ac4c.c
[nano-query]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/001a5d08.c
[mini-member]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00053860.c
[separator]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00069b4c.c
[overlap]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/0009c6e8.asm.txt

[index]: ../../.scratch/calendar-exceptions-spans-index-20261109-v3.json
[cross]: ../../.scratch/calendar-exceptions-spans-cross-20261109-v1.json

## Later-model list values and repeated properties, 2026-11-10

The [ARM list-value receipt](../../.scratch/calendar-later-date-lists-20261110.json)
and [Thumb list-value receipt](../../.scratch/calendar-thumb-date-lists-20261110.json)
execute eight fixtures independently on each of Video 13/20/25, Classic
24/33/35/38 and Nano 3/4/5: **80 fixtures and 640 actual day queries**, all
passed. Each fixture executes original RDATE/EXDATE property handlers, native
date-list construction/parsing, collection adoption and the actual event query.
Input objects contain a floating November 1, 2026 source span at 09:00–10:00.
Matched queries assert both the accepted day and the exact returned source-time
span. Input property names and values are UTF-16 spans, not Host-expanded dates.

| Fixture | Explicit entry flags | Observed day offsets from source |
| --- | --- | --- |
| Semicolon-separated RDATE days 2 and 4 | First flag 0, second flag 0 | 0, 2, 4 |
| Comma-separated RDATE days 2 and 4 | First flag 0, second flag 0 | 0, 2 |
| Comma-separated RDATE days 2 and 4 | First flag 1, second flag 0 | 0, 2, 4 |
| Semicolon-separated RDATE days 2 and 4 | First flag 1, second flag 0 | 0, 2 |
| Two separate RDATE properties, day 2 then day 4 | 0, 0 | 0, 2, 4 |
| RDATE days 2/4/6, then separate EXDATE properties for 2 and 4 | 0, 0 | 0, 6 |
| Date-only RDATE days 2 and 4 | 0, 0 | 0, 2, 4 |
| RDATE days 2/4 at 15:00, then EXDATE day 2 at 23:00 | 0, 0 | 0, 4 |

Thus repeated RDATE and repeated EXDATE **union** their lists on these actual
handler/adoption paths. They do not implement last-property replacement. The
date-list match ignores the added/excluded time in these fixtures and returns
the source event's 09:00–10:00 span. A date-only value here is a tested property
value, not a claim that every VALUE=DATE parameter combination is supported.

The two explicit flag bytes are entry-parser offsets `+0x84` and `+0x85` on
these later targets. This test supplies them directly and must remain distinct
from a root VERSION-to-child-construction test. The Mini 2 stream-boundary tests
above establish that longer chain only for Mini 2. Neither a generic character
source nor a filesystem reader participates in the later-model fixtures.

### Native root VERSION comparison on the ten later inputs

The [ARM VERSION receipt](../../.scratch/calendar-later-version-flags-20261110.json)
and [Thumb VERSION receipt](../../.scratch/calendar-thumb-version-flags-20261110.json)
add **30 original-instruction cases** across those same ten images. Each native
root VERSION handler compares its input against the actual token **1.0**, read
and asserted from that image's own token table. VERSION:1.0 sets root `+0x90`
to one; VERSION:2.0 and the diagnostic value 9.9 leave an initially zero flag
unchanged. The downstream format-application call is a recording adapter;
native string comparison and the flag store execute. Unknown-version acceptance
by a complete Calendar parser is not established by the unchanged flag.

These results separately qualify root version selection and entry flag/list
semantics. They do not substitute an assumed child flag transfer or a whole-root
stream parse. The Mini 2 chain must not be silently transferred to later models.

### Native execution and adapter boundaries

Video uses its independently validated original startup/map loader. Classic and
Nano 3 need allocation and fixed-thread-identifier adapters. Repeated-list merge
also reaches heap release: because those allocations are synthetic Host-backed
blocks without native heap headers, the release adapter applies **only to known
synthetic allocation pointers**. Other pointers retain native handling. Native
collection iteration/merge and all original query results still execute; the
earlier assertion from feeding a synthetic pointer to an unadapted native heap
release is a harness limitation, not firmware rejection of repeated properties.

Nano 4 uses its original-map loader and an equivalent bounded synthetic release
adapter at `0x081637fc`. Nano 5 uses the previously qualified string heap,
C++ allocation/free and thread adapters, plus the explicitly recorded flat-map
TLB-invalidation skip. The source and image identities in the receipts bind the
actual routines, rather than inferring behavior from shared model names.

The [retained source bundle](../../.scratch/calendar-later-lists-sources-20261110/manifest.json)
records four receipt hashes and thirteen exact source copies, including native
loaders and adapter implementations. Every receipt's harness hash was rechecked
against its retained source. Earlier exploratory runs and receipts remain intact.
No app code or physical device files were changed.

## Complete Mini 2 root streams and source-interface correction

The [27-stream index](../../.scratch/calendar-mini2-root-stream-20261110/index.json)
and [matrix runner](../../.scratch/run_mini2_root_stream_matrix_20261110.py)
close the earlier Mini 2 multi-property source limitation. The
[native harness](../../.scratch/probe_mini2_stream_parameters_20261110.py)
implements source-vtable slot `+4` as **unread one character**, asserting that
the supplied character equals the last consumed character before moving back.
The original [line-fold lookahead](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/0007e4f4.c)
uses this operation when its lookahead is not a continuation space or tab.
Treating that slot as a no-op dropped the first character of subsequent lines.
The earlier apparent property skipping was an adapter error.

Each new case supplies a complete `BEGIN:VCALENDAR` through `END:VCALENDAR`
character stream, including VERSION, PRODID, one VEVENT, DTSTART and DTEND.
The original aggregate constructor `0x000e2f44`, root constructor `0x000e759c`,
root parsing entry `0x000a0b5c`, VERSION handler, root-to-child construction,
entry handlers, finalization/adoption and full query all execute. In particular,
the [native VEVENT route](../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00078ed8.asm.txt)
supplies the root version flag to the child; it is not manually copied by this
probe. Observers record handler input and event adoption without replacing them.

All 27 streams are consumed completely. Each receives eight original event
queries, totaling **216 queries**, with exact returned 09:00–10:00 source-time
spans asserted. Results confirm the earlier version table: VERSION:1.0 selects
comma lists; VERSION:2.0 selects semicolon lists in this Mini 2 path. With the
other delimiter, only the first supplied date contributes in these fixtures.
Separate RDATE and EXDATE properties merge in either tested order, folded lists
work, an empty later RDATE preserves the earlier additions, and supplied added-
date times do not replace the source event's times.

The Mini 2 probe uses an ASCII fixture character source with synthetic heap
allocation, reallocation and release. Byte decoding, filesystem opening, live
adoption and other component combinations remain open. The native parser takes
a Calendar aggregate. Earlier exploratory calls supplied an unrelated object
or omitted that argument. The complete-stream matrices use the original
aggregate constructor on each target. [Firmware coverage matrix](calendar-firmware-coverage-2026-11-08.md)

## VALUE and TZID date-list parameters on all thirteen images

The parameter matrix executes **28 fixtures independently on each of all 13
readable Calendar-capable images: 364 fixtures and 2,912 native day queries**.
Every fixture runs original RDATE/EXDATE callbacks, date-list construction and
parsing, native collection adoption and full event queries. Both accepted day
offsets and exact returned source-time spans are checked. Entry flags are supplied
explicitly as zero in this matrix; the Mini 2 complete-root experiment above
independently tests its longer framing path.

Primary receipts are the
[eight ARM targets](../../.scratch/calendar-later-date-parameters-20261110.json),
[Nano 4/5](../../.scratch/calendar-thumb-date-parameters-20261110.json),
[Mini 1](../../.scratch/calendar-mini1-date-parameters-20261110-v3/receipt.json),
[Mini 2](../../.scratch/calendar-mini2-date-parameters-20261110-v3/receipt.json), and
[Nano 1](../../.scratch/calendar-nano1-date-parameters-20261110-v3/receipt.json).
The source day is November 1, 2026 at 09:00–10:00. Added dates are days 2 and 4;
the exclusion control removes day 2 using a supplied 23:00 time.

| List-property header | Added-date result | Excluded-date result after adding days 2/4 |
| --- | --- | --- |
| Bare RDATE or EXDATE | 0, 2, 4 | 0, 4 |
| `VALUE=DATE-TIME` | 0, 2, 4 | 0, 4 |
| `VALUE=DATE` | 0 | 0, 2, 4 |
| `VALUE=PERIOD` | 0 | 0, 2, 4 |
| `TZID=Missing/Zone`, `TZID=Z`, or quoted missing name | 0, 2, 4 | 0, 4 |
| TZID plus `VALUE=DATE`, either tested parameter order | 0 | 0, 2, 4 |
| TZID plus `VALUE=DATE-TIME`, either tested parameter order | 0, 2, 4 | 0, 4 |
| Lowercase `value=date` | 0 | 0, 2, 4 |

Bare eight-digit date values also add/exclude the expected days, while the same
values with explicit `VALUE=DATE` do not. This is a native parser quirk, not a
reason to rewrite imported bytes or replace the result with generic RFC behavior.
On Mini 2, original instruction inspection independently explains it: the
date-list parameter consumer `0x0009fb14` compares VALUE against the image's
`date` and `period` tokens and clears the processing flag at object `+0x18`.
`VALUE=DATE-TIME` does not take that disable branch in these fixtures. The complete
Mini 2 streams confirm that VALUE reaches the actual callback intact before the
native list parser makes this decision.

The tested TZID spellings leave date membership unchanged. This does **not**
establish event-zone resolution or timezone conversion: these list paths retain
the existing source-time span, and no populated Calendar-zone resolver is supplied
to them. Quoted VALUE, arbitrary parameters, mixed date representations within
one property and other framing modes remain outside this matrix.

The legacy matrix keeps synthetic allocation addresses distinct between cases.
An earlier harness rewound its heap while retaining the native machine's other
state; the next combined-list control then failed even on Mini 2. Preserving the
allocation lifetime fixes that control on Mini 1/2 and Nano 1. Those exploratory
failures are not additional firmware behavior. Later-target adapters retain their
previous bounded heap/free/thread and Nano 5 cache/TLB boundaries.

The [validation/source manifest](../../.scratch/calendar-parameter-and-zone-sources-20261110/manifest.json)
independently verifies all five parameter receipts, all 27 complete-root receipts,
the populated-zone receipt and their retained harness copies. It records 25 exact
source copies, shared fixture inputs and receipt hashes. This extends research
coverage without changing app authoring, projection or import-normalization rights.
