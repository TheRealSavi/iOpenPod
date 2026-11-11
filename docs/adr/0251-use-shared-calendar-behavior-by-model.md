# ADR-0251: Use shared Calendar behavior by model

- Status: Accepted
- Date: 2026-11-11
- Supersedes: ADR-0249 for Calendar
- Amends: ADR-0247 for Calendar

## Decision

Device Registry exposes Calendar for Mini 1/2, Nano 1–5, Video and Classic
through their Device Profiles. Calendar reads and writes use one format
implementation in iPodDB without requiring a RetailOS version or updater
family. The Application Layer continues to require the current Active iPod,
its Filesystem Session and an issued Calendar catalog. Storage checks the
captured source files and publishes changes in a Storage Transaction.

Nano 2 follows the shared model policy by user direction. Its encrypted image
remains an evidence gap in the firmware lab. Nano 6/7 explicitly report that
Calendar is unavailable. Clock Alarm writes retain their own firmware and file
layout qualification. [Firmware evidence](../research/calendar-firmware-coverage-2026-11-08.md)

Calendar is available in both navigation styles. The Extras development flag
continues to control the Alarms page. The file editor writes recognized fields
in a single iCalendar 2.0 container. Both version 1.0 and 2.0 can be inspected
and projected. Unnamed imports retain their original bytes and unrecognized
properties remain in the saved file.

## Shared Calendar behavior

| Area | Implemented behavior |
| --- | --- |
| Repeat rules | Daily, weekly, monthly and yearly with interval, COUNT or inclusive floating UNTIL. The editor accepts the exact cutoff date and time through seconds. Monthly seed days skip short months, and yearly leap-day anniversaries skip non-leap years. |
| Repeat selectors | Daily and weekly weekdays, weekly start of week, monthly days of month and ordinal weekdays, monthly last matching weekday, and yearly month/day filters. |
| Repeat exceptions | Added and excluded civil dates and an exclusion rule. Repeated lists merge. Version 1.0 uses commas and 2.0 uses semicolons. The tested explicit DATE/PERIOD list parameters leave membership unchanged. |
| Calendar Occurrences | A day query selects the first overlapping accepted span, with the saved source span as fallback. All-day ends are exclusive. A projected repeat can be skipped by appending its start date to EXDATE. |
| Timezones | Event TZIDs bind to definitions already read in the same Calendar. The editor offers local time, UTC and usable named zones at the event's file position. Changing the timezone keeps the displayed clock time. |
| Calendar Reminders | One saved trigger, with signed second offsets relative to start or end, or an absolute civil or UTC value. A trigger edit preserves other fields in its VALARM. |
| To Dos | Open, In progress, Completed and Cancelled. The writer uses the native STATUS tokens and preserves existing progress metadata. |

Occurrence queries cover at most 63 days. The implementation bounds the COUNT
search at 10,000 days and uses the observed year-3000 recurrence limit. Rule
combinations outside the supported selectors keep their saved dates and bytes.
Detached entries remain separate. A matching exclusion can suppress an expanded
date while the day query still returns the saved source span. These rules come
from the complete event query and the finalized recurrence model.
[Repeat evidence](../research/calendar-advanced-recurrence-2026-11-09.md),
[exception evidence](../research/calendar-exceptions-and-spans-2026-11-09.md)

Calendar shows saved civil time for floating and named-zone values and explicitly
labels UTC. Zone lookup follows the tested ASCII case comparison and source
order. Ambiguous duplicate zone names remain preserved. The time context used by
the live device query is outside saved Calendar files. The application keeps
observance properties and uses the zone to interpret the saved event association.
[Timezone evidence](../research/calendar-stream-timezone-binding-2026-11-11.md)

The reminder editor saves trigger bytes and can display the civil result of
applying a relative trigger to the saved event. Imported ambiguous or multiple
triggers retain their original bytes. The app leaves hardware delivery, sound
and live activation to the iPod. [Reminder evidence](../research/calendar-timezones-and-reminders-2026-11-09.md)

## Validation

Codec tests cover the native weekday, monthly, yearly, exception and multi-day
vectors, timezone binding and source preservation. Registry tests cover missing
and conflicting firmware metadata, Nano 2 and the Nano 6/7 exclusion. Virtual
Storage tests verify transaction publication and show that changing firmware
metadata after capture does not invalidate a Calendar edit. GUI tests exercise
navigation and the typed editor controls.

The implementation also matches 5,016 recorded native span and exception day
queries, 2,808 complete-stream day queries and all 169 recorded event-zone
bindings. The comparisons use the original lab receipts as expected results.
