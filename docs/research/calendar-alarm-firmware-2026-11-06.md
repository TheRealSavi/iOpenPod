# Calendar and Alarm applications across the latest click-wheel firmware

Research date: 2026-11-06. This continues the [Mini/Video clock investigation][earlier]
and [Classic date-file map][files]. Scope is Mini 2 / 1.4.1, Video 5/5.5 / 1.3,
and Classic updater families 24 / 1.1.2, 33 / 2.0.1, 35 / 2.0.4 and 38 / 2.0.5.
Original firmware is inspected offline. Native probes use emulated instructions
and explicit substitute I/O; they do not establish physical wake or sound output.

The [calendar naming follow-up](calendar-names-and-groups-2026-11-08.md) traces
Classic 2.0.1's `X-WR-CALNAME` selection and identifies the application's missing
calendar identity behind the reported Other grouping. It separates multiple-file
capture, named Calendar objects and flat event presentation.

The later [Mini recurrence qualification](calendar-recurrence-qualification-2026-11-08.md)
and [Classic reminder qualification](calendar-reminder-qualification-2026-11-08.md)
execute narrower native paths that this original inventory left open. They
qualify Mini 2's bounded floating daily/weekly occurrence subset separately from
the four latest Classics' single start-relative saved reminder. See
[ADR-0249](../adr/0249-qualify-calendar-occurrences-and-reminders-by-firmware.md)
for implemented capabilities and targets; the other open questions below remain.

## Keep the three alarm paths separate

| Path | Meaning | Evidence needed before equating it with another path |
| --- | --- | --- |
| Imported Calendar reminder | An alarm attached to an event or task, interpreted with that calendar document's date rules | Property dispatch, event association, trigger calculation and notification path |
| Alarm app entry | An on-device alarm with a time, enable state, sound/Playlist and potentially repeat/date/city settings | Saved record layout, next-occurrence calculation and reload behavior |
| Hardware wake alarm | A programmed hardware calendar/interrupt used to wake or notify firmware | Scheduler ownership, register writes, interrupt handling and power-state behavior |

The sleep timer is another consumer: its user-visible duration is not an imported
calendar event or historical media timestamp. A function that writes RTC alarm
registers does not by itself establish which user-visible alarm caused the write.
The distinction follows the firmware call graphs, not a shared English label.

## New native findings

### Mini 2 / 1.4.1

The actual Calendar directory callback, event/property dispatchers, timezone
observances and alarm refresh route are identified. Native property parsing
retains a supplied TZID string; a trailing uppercase `Z` replaces it with the
UTC marker. A numeric DATE-TIME suffix is ignored by the tested leaf, while a
separate offset-property parser understands `+0530` as 19,800 seconds. Invalid
components can enter ordinal/seconds arithmetic. These are executed property
paths, not complete-file acceptance tests. [Mini report][mini]

The most consequential distinction is in evaluation: one event-query converter
chooses standard/daylight observance using the device's **current DST state**.
A different parsed-UTC wrapper chooses the supplied zone's standard observance.
January/July probes with constructed native zone objects distinguish both paths.
They do not establish every VTIMEZONE transition rule or upstream default-zone
choice. Historical IANA interpretation in iOpenPod remains a Host estimate,
rather than a reproduction of those native choices. [Timezone experiments][mini]

Native interval matching excludes touching endpoints, supporting an exclusive
event end in that query path. Modern recurrence parsing retains tested
DAILY/WEEKLY/MONTHLY/YEARLY fields, interval/count and UNTIL; expansion and
exceptions remain a separate investigation. Relative alarm triggers distinguish
START from END; absolute triggers construct a different object. [Event and alarm probes][mini]

The Mini Alarm Clock stores its word at Preferences `+0xb22`, separate from the
timezone menu at `+0xb10`. Its next-occurrence calculation advances to tomorrow
when the requested time is **five seconds or less away**. Six seconds ahead
stays today. Clock and Calendar alarms feed separate slots of a five-slot
selector; native probes execute BCD alarm-register writes for the selected slot.
Static Calendar refresh searches through now plus 90 days, and a property-change
callback reschedules the Alarm Clock for timezone/time/mode changes. Physical
wake, sound delivery and the complete notification subscription graph remain
open. [Settings, scheduling and callbacks][mini]

### Video 5/5.5 / 1.3

Families 13, 20 and 25 were loaded and checked independently, including the
complete family-25 image with its extra trailing bytes. The Calendar route
recognizes event/task, timezone, recurrence and alarm components. Date properties
retain a civil day/seconds pair and the supplied timezone name; uppercase `Z`
overrides that name. Retaining a name does not establish its resolution or
historical offset. Event start/end storage is mapped, but exclusive-end query
behavior is still unqualified. [Video parser and event findings][video]

Native recurrence construction produces DAILY/WEEKLY/MONTHLY/YEARLY objects
with tested interval, count and UNTIL fields. It does not yet prove the expanded
occurrences. Relative VALARM triggers retain START/END selection and signed
durations; absolute triggers construct a separate object. The tested duration
scanner returns zero for `-P1W`, so even a standard-looking duration must not be
assumed to have its standard meaning on the device. [Recurrence and trigger probes][video]

The Clock app's next-alarm calculation translates between current and selected
clock offsets, each including its supplied manual-DST flag. It drops current
seconds: an alarm at the current minute advances to tomorrow, whereas 01:29:50
still permits today's 01:30 alarm. A gap-shaped 02:30 remains a civil candidate;
this function does not consult timezone transitions. The resulting 1970-based
scalar represents the current clock's civil basis, not an established UTC
instant. [Clock app scheduling vectors][video]

The generic alarm programmer selects from five slots and calls the BCD writer.
The manual calendar setter directly calls that programmer. Registration accepts
an additional index 5 which the inspected selector does not scan; its purpose
remains unknown. Static dispatch identifies notification delivery, but complete
application registrations, timezone/DST recomputation and physical wake/audio
still need tracing. [Alarm pool and clock-change paths][video]

### Latest Classics: Calendar parser and reminders

All four exact images independently retain the tested civil date pairs and
TZID parameters. A separate Calendar-owned lookup installs a found zone and
leaves the existing zone pointer unchanged when lookup fails. The lookup result
is substituted in these tests: this proves the gate, not built-in IANA support
or VTIMEZONE transition evaluation. Calendar Zone lookup is separate from the
Device city table and `Device/dst`. [Per-image Calendar evidence][classic-calendar]

The parsers are permissive at the tested boundaries: February 30 becomes a
March ordinal, numeric DATE-TIME offset suffixes are ignored, and `P2W`
produces a zero duration. This is not proof that the complete file loader
accepts every such input. Relative VALARM parsing supplies signed seconds and
START/END selection. Absolute-trigger parsing passes floating and `Z` inputs
as identical day/seconds pairs at the observed constructor boundary; later
timezone interpretation remains open. [Date and trigger probes][classic-calendar]

Native frequency handlers recognize daily, weekly, monthly and yearly values.
Static dispatch also identifies INTERVAL, COUNT, UNTIL and BY* handlers, but
Calendar recurrence expansion is not covered by the Alarm app repeat tests
below. Exclusive event ends, exception merging and alarm recalculation following
clock changes remain separate questions. [Recurrence limits][classic-calendar]

### Latest Classics: Alarm file and repeat engine

All four exact images independently execute the same bounded persistence,
repeat and earliest-selection contracts. Their Alarm app uses
**`iPod_Control/Device/alarms`**, a little-endian token stream. Container `0x3a`
holds record containers `5`; field `6` carries the scheduled u32 scalar and
field `0x3b` the repeat mode. String fields include their terminating NUL.
The format is variable-length, so object offsets are not fixed file offsets.
Other selector/control/string meanings remain partially unidentified.
[File layout, per-image addresses and receipt][classic-alarms]

The probed alarm conversion uses a **1970 calendar coordinate**, distinct from
the 1904 media-date coordinate. Its complete producer's UTC/local provenance is
still open. Native repeat modes distinguish none, daily, weekdays, weekends,
weekly, monthly and annual advancement. A January 31 monthly alarm clamps to
February 28 and restores March 31 when its in-memory original-day anchor is 31.
That anchor's post-reload source is not yet established. An annual February 29,
2024 probe advances to March 1, 2025. [Repeat vectors and limits][classic-alarms]

Earliest selection honors a nonzero postponement override, skips certain
ineligible objects, and retains the first equal deadline. Zero is eligible;
`0xffffffff` is not selected because it equals the search's initial upper bound.
A matched postpone handler adds 540 seconds, but its complete UI and wake
behavior is not executed. These facts must not become new media-date sentinel
rules. [Selection and postpone evidence][classic-alarms]

## Manual baseline

Apple's Mini 2 manual exposes its alarm under Extras > Clock, with a beep or
Playlist sound, and a separate sleep timer. Its Calendar app displays imported
events and tasks. [Mini manual, printed pages 37–41][mini-manual]

The Classic 120GB and later 160GB guides describe an Alarms screen, created alarm
entries with date/time, repeat options, sound and labels, plus a sleep timer.
They also describe additional city clocks and imported Calendar/task files.
These are product-level observations, not qualification of a private disk format
or a particular firmware's repeat algorithm. [120GB guide, pages 49–55][classic-manual],
[160GB guide, pages 41–46][later-manual]

## Standards are a comparison, not firmware acceptance evidence

RFC 2445 distinguishes date-only values, floating local times, UTC values with
`Z`, and local times associated with a `TZID`/`VTIMEZONE` definition. An event's
`DTEND` is exclusive. A relative `VALARM` trigger defaults to the associated
start; an absolute trigger is UTC. Alarm `REPEAT`/`DURATION` describe repeated
notifications, separately from event recurrence. A `TZID` need not be a usable
Host IANA database key. These distinctions must survive any future semantic
model. [RFC 2445, sections 4.2.19, 4.3.5, 4.6.1 and 4.8.6][rfc2445]

RFC 5545 forbids a numeric UTC-offset suffix in a DATE-TIME value. Its explicit
local date interpretation selects the first fold occurrence and the pre-gap
offset; its recurrence expansion instead omits generated invalid or nonexistent
local instances. Those are different operations. A permissive native parser is
not necessarily a recurrence evaluator, and modern standard behavior is not proof
of an older firmware implementation. [RFC 5545, sections 3.3.5 and 3.3.10][rfc5545]

The comparison matrix therefore includes `20261101`, `20261101T013000`, a `Z`
suffix, a named-zone parameter, a deliberately nonconforming `+0530` suffix,
malformed fields, exclusive event ends and a `TRIGGER:-PT15M` reminder. A leaf
parser accepting text is weaker evidence than the complete file loader accepting
it, displaying an event and scheduling the correct notification. `.vcs` support
also needs its own grammar qualification; an extension is not proof of RFC parity.

## Questions still open for each target

Every target still needs full-file fixtures for folding, escaping, encodings,
bounds and recovery; occurrence-level VTIMEZONE/recurrence/exception tests; and
complete Calendar alarm action, repeat, dismissal and notification tracing.
Physical wake, audio and missed-alarm behavior remain untested on every target.
These common gaps do not disappear when a nearby function matches another image.

| Target and latest firmware | Additional questions to carry forward |
| --- | --- |
| Mini 2 / family 7 / 1.4.1 | How are Calendar Zone observances/defaults built before the current-DST converter? How do the legacy VERSION 1.0 recurrence path, missing event end and absolute alarm zone behave? What completes property-change subscriptions and hardware interrupt delivery? |
| Video 5 / families 13 and 20 / 1.3 | Where is exclusive DTEND enforced? Which Clock/Calendar callers register generic alarm slots, what uses index 5, and which timezone/DST changes recompute pending alarms? |
| Video 5.5 / family 25 / 1.3 | The same questions remain independently open on this complete image: event-end semantics, application slot registrations, index 5 and timezone/DST recomputation. |
| Classic 6 / family 24 / 1.1.2 | What is the live Alarm scalar's UTC/local provenance, how is the monthly original-day anchor restored, and what do the remaining record fields mean? How do Calendar reminders and Alarm entries reach wake scheduling after clock changes? |
| Classic 6.5 / family 33 / 2.0.1 | The same persistence and scheduling questions remain. A static alarm-to-calendar bridge adds 60 seconds before programming; its purpose and physical effect are unqualified. |
| Classic 7 / family 35 / 2.0.4 | The same persistence and scheduling questions remain independently open; family 33's extra bridge observation is not an established contract here. |
| Classic 7.5 / family 38 / 2.0.5 | The same persistence and scheduling questions remain independently open; family 33's extra bridge observation is not an established contract here. |

The most useful next offline increment is to drive a complete Calendar document
through timezone and recurrence evaluation, then trace the resulting reminder
into its scheduler slot. For Alarm app persistence, follow the reload constructor
and live current-time producer before assigning stronger timestamp semantics.
Hardware behavior requires a separate device experiment after those paths are
understood. [Mini questions][mini], [Video questions][video],
[Classic Calendar questions][classic-calendar], [Classic Alarm questions][classic-alarms]

## Validation and reproducibility

| Probe | Exact inputs | Passing native cases | Final receipt |
| --- | --- | ---: | --- |
| Mini Calendar/Alarm | Family 7 / 1.4.1 | 54 | [Mini receipt][mini-receipt] |
| Video Calendar/Alarm | Families 13, 20 and 25 / 1.3 | 141 | [Video receipt][video-receipt] |
| Classic Calendar | Families 24, 33, 35 and 38, versions above | 220 | [Calendar receipt][classic-calendar-receipt] |
| Classic Alarm persistence/repeat | The same four independently loaded images | 112 | [Alarm receipt][classic-alarm-receipt] |

The total is **527 cases**, executing original ARM instructions with explicit
substitutions for selected allocations, I/O and caller state. The reports name
those boundaries, record source/script/instruction hashes and separate static
call-graph findings from executed behavior. These counts are not whole-application
or physical-device tests. No device writes or new production Calendar/Alarm
implementation were needed for this research increment.

## Application boundaries

At the time of this November 6 research, iOpenPod had no Calendar/Alarm editor,
event recurrence engine or calendar-file parser. The source search and Original iOpenPod baseline
at `a20242428b93b672d14b37230772dbad75139c69` establish no existing Python
VCALENDAR/VTIMEZONE/VALARM implementation to port. This research is format and
behavior groundwork, not an implicit promise that Sync authors these artifacts.

The November 7 implementation in [ADR-0247][extras-policy] adds a separate Extras
workflow: bounded Calendar inspection, simple event/To Do authoring, unchanged
imports and existing Alarm field edits. Recurrence expansion, new Alarm defaults,
remote Sleep Timer control and physical wake acceptance remain unresolved.

Backup enumeration traverses ordinary files without parsing calendar contents.
`Calendars`, alarm records and unknown date-bearing files are not special
exclusions. That preservation behavior is independent of whether their dates
can be interpreted; normal Storage identity, filesystem and recovery requirements
still apply. [Backup scope][backup]

The [nonblocking date policy][policy] remains in force. For future Calendar
support, preserve source text, unknown properties and the value's original kind;
do not eagerly turn every date into a Unix instant. An all-day date is not a UTC
midnight, a floating time is not a Host-zone timestamp, a relative trigger is a
duration, and an alarm time of zero may mean midnight. Existing media-date
sentinels must not be transferred to these fields without evidence.

Captured Device Time Context remains a Library interpretation input. It must not
silently replace document-local `VTIMEZONE` rules or inject saved DST twice into
an already adjusted value. Uncertain optional Calendar interpretation must not
become a Library load, playback reconciliation or Sync precondition. Exact native
bytes remain available when an interpretation is incomplete.

[earlier]: mini-video-datetime-firmware-2026-11-06.md
[files]: classic-datetime-file-map-2026-11-06.md
[mini-manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma96_ipod_mini_2nd_gen_userguide.pdf
[classic-manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf
[later-manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma1195_ipod_classic_160gb_user_guide.pdf
[rfc2445]: https://www.rfc-editor.org/rfc/rfc2445
[rfc5545]: https://www.rfc-editor.org/rfc/rfc5545
[backup]: ../../src/iOpenPod/app/backups/scope.py
[policy]: ../adr/0240-treat-calendar-dates-as-best-effort-metadata.md
[extras-policy]: ../adr/0247-manage-extras-through-qualified-lossless-file-edits.md
[mini]: ../../../ipod-firmware-lab/notes/mini2-calendar-alarm-2026-11-06.md
[video]: ../../../ipod-firmware-lab/notes/video-calendar-alarm-2026-11-06.md
[classic-calendar]: ../../../ipod-firmware-lab/notes/classic-calendar-alarm-2026-11-06.md
[classic-alarms]: ../../../ipod-firmware-lab/notes/classic-alarm-persistence-2026-11-06.md
[mini-receipt]: ../../../ipod-firmware-lab/artifacts/mini2-calendar-alarm-20261106-v4/receipt.json
[video-receipt]: ../../../ipod-firmware-lab/artifacts/video-calendar-alarm-20261106-v1/native-v6.json
[classic-calendar-receipt]: ../../../ipod-firmware-lab/artifacts/classic-calendar-native-20261106-v6/receipt.json
[classic-alarm-receipt]: ../../../ipod-firmware-lab/artifacts/classic-alarm-20261106-v1/native-v7.json
