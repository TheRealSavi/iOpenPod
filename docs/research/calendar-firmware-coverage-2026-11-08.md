# Calendar coverage across the firmware lab

The application qualifies Calendar separately from Clock Alarms and from
Preferences. A Calendar writer does not grant either other writer. Native
availability, a parsed property, evaluated occurrences and physical reminder
delivery are different evidence levels.

The [shared Calendar decision](../adr/0251-use-shared-calendar-behavior-by-model.md)
records the application authoring and projection policy. Basic editing includes
events, To Dos, calendar creation/renaming, named imports and destination selection;
unsupported imported fields and component bytes remain retained.

## Per-target evidence

- [Mini 1/2 and Nano 1](calendar-legacy-coverage-2026-11-08.md): independently
  executed Calendar/name/property callbacks, reminder constructors, relative
  triggers and To Do defaults, with exact image identities and private receipts.
- [Video and Classic](calendar-classic-video-coverage-2026-11-08.md): independently
  executed recurrence construction, full event membership and returned spans on
  all seven images, plus Video reminder qualification. The earlier
  [Classic reminder report](calendar-reminder-qualification-2026-11-08.md) remains
  the source for those four reminder writers.
- [Nano coverage](calendar-nano-coverage-2026-11-08.md): exact native Calendar
  dispatch and reminder consumers on Nano 3/4/5, explicit negative capability
  results on Nano 6/7, and Nano 2's encrypted-evidence limitation.

## Important limits

### Advanced investigation follow-up, 2026-11-09

The next investigation separates native property parsing from complete event
queries and records additional behavior in four reports:

- [Advanced recurrence](calendar-advanced-recurrence-2026-11-09.md).
- [Exceptions and event spans](calendar-exceptions-and-spans-2026-11-09.md).
- [Timezones and reminder evaluation](calendar-timezones-and-reminders-2026-11-09.md).
- [Reload and delivery boundaries](calendar-reload-and-delivery-2026-11-09.md).

Each report states its executed targets, adapters and remaining gaps. ADR-0251
records which shared results are used by the application.

Subsequent whole-event work is recorded in the linked reports. In particular,
the earlier bare-YEARLY property-predicate result is a **pre-finalization** result:
native event finalization adds defaults before normal event use. It must not be
implemented as the user-visible semantics of a completed Calendar event.

| Investigation | Executed targets | Established layer |
| --- | --- | --- |
| Advanced monthly/yearly recurrence | Video 13/20/25, Classic 24/33/35/38, Nano 3/4/5; parsed Mini 1/2 and Nano 1 probes | Modern constructor/event-membership parity; parsed legacy monthly rules agree with Video despite different raw-constructor defaults |
| BY* and WKST | All 13 readable Calendar-capable images | Twelve selected parsed-rule vectors agree; not every compound rule or finalization path |
| Finalized leap-day YEARLY | All 13 readable Calendar-capable images | Native event finalization establishes defaults; anniversaries skip non-leap years |
| EXRULE, all-day and multiday spans | All 13 readable Calendar-capable images | Candidate predicates and full-query fallback, with explicit source spans |
| RDATE/EXDATE values and parameters | All 13 readable Calendar-capable images | Native handlers, merging and queries; 28 VALUE/TZID fixtures per image; explicit DATE/PERIOD disable the tested list path |
| Complete root text framing | All 13 readable Calendar-capable inputs | 27 streams per input verify native VERSION transfer, parsing, event adoption and day queries |
| UID/RECURRENCE-ID dispatch | All 13 readable Calendar-capable images | Tested entry callbacks ignore both; not a proof about every collection/import route |
| Relative END and absolute trigger evaluation | All 13 readable Calendar-capable images | Trigger leaves; no complete timezone/scheduler or physical delivery claim |
| Reminder slot replacement | Video 13/20/25 and Classic 24/33/35/38 | Native adoption replaces a prior trigger; an empty holder clears it; no full-file duplicate-component claim |
| Current-DST versus standard-offset conversion | All 13 readable Calendar-capable images | Native conversion paths; Video/Classic/Nano 1/3 also have parsed transition objects; Nano 4/5 use offset-only objects |
| Fresh/populated Calendar zone lookup | Video 13/20/25, Classic 24/33/35/38 | Fresh constructor adds zero-offset Z; tested ASCII case variants match, miss preserves prior pointer; duplicate selection has no simple first/last rule in tested vectors |
| Timezone binding in complete streams | All 13 readable Calendar-capable inputs | 13 streams per input verify native zone adoption, order-dependent event binding, floating dates, zero-offset Z and exact stored spans |
| Collection reload orchestration | Mini 1/2 | Reload wrapper and request-enqueue helper with explicit OS/filesystem/publication adapters; real event trigger remains unresolved |
| Software reminder delivery task | Mini 1/2 | Ten bounded task cases execute processed-flag clearing, optional wake request, token signaling and reselection calls; OS receiver and physical delivery remain unresolved |

The 2026-11-10 list follow-up adds 80 fixtures and 640 native day queries on all
ten later inputs, plus 30 actual VERSION-handler comparisons. Repeated RDATE and
EXDATE collections merge rather than replacing earlier properties. Four separate
Mini 2 handler/query tests independently confirm the repeated-property result.
The source-interface audit identified an unread-character operation previously
adapted as a no-op. Correcting it closes the Mini 2 multi-property gap: 27 complete
root streams and 216 native queries verify VERSION-to-child framing, repeated
lists, folding and parameter routing. Older skipped-property outputs remain
adapter failures, not firmware semantics.

A further 28 parameter fixtures on each of all 13 images add **2,912 native day
queries**. Bare dates work, but explicit VALUE=DATE/PERIOD disable the tested
date-list path; VALUE=DATE-TIME does not. Tested TZID spellings leave this list
membership unchanged without establishing event-zone resolution. Populated-zone
work on the seven Video/Classic images corrects the earlier empty-collection
description: a fresh Calendar contains Z. It also establishes tested name matching,
315 assignment-gate vectors and collection-dependent duplicate selection.

The 2026-11-11 follow-up extends the 27 complete recurrence streams to twelve
more inputs. The total is **351 streams and 2,808 day queries** across all 13
readable Calendar-capable inputs. A separate timezone matrix covers **169 streams
and 1,014 native name lookups** on those same inputs. In the tested files, the
event binds a zone defined before it. A later definition enters the Calendar
without updating the earlier event. Floating dates leave the event zone empty,
and both the `Z` suffix and
`TZID=Z` bind the built-in object. [Mini and Nano 1 streams](calendar-legacy-coverage-2026-11-08.md#complete-calendar-streams-2026-11-11),
[Video, Classic and Nano 3/4/5 streams](calendar-video-classic-streams-2026-11-10.md),
[timezone binding results](calendar-stream-timezone-binding-2026-11-11.md)

Open questions include mixed timezone transition components, duplicate TZIDs in
full text, byte decoding and file enumeration. Real reload triggers, the OS
notification receiver and physical reminder delivery also remain open. Nano 2
still requires readable firmware evidence.

### Remaining qualification boundaries

Nano 6 / 1.2, Nano 7 / 1.0.4 and Nano 7 / 1.1.2 explicitly register
`iCalendarsSupported=0`. Retained Calendar strings do not qualify a Calendar
workflow on those targets. Clock Alarms are separate.

Nano 2 updater families 19/29 share encrypted firmware 1.1.3. The lab currently
has no accepted plaintext OSOS or decompilation for that image. Its native
Calendar behavior remains unknown in the lab. iOpenPod includes Nano 2 under
the shared model policy by user direction. [Application decision](../adr/0251-use-shared-calendar-behavior-by-model.md)

Inspected To Do consumers recognize COMPLETED, IN-PROCESS and CANCELLED, and
fresh objects default to open. The editor writes the recognized status tokens
and reopens an item by removing STATUS and the old completion timestamp.
Existing percentage metadata stays intact.

Saved reminders describe persisted TRIGGER bytes. Live adoption, wake and audio
delivery remain separate questions.
