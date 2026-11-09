# Calendar coverage across the firmware lab

The application qualifies Calendar separately from Clock Alarms and from
Preferences. A Calendar writer does not grant either other writer. Native
availability, a parsed property, evaluated occurrences and physical reminder
delivery are different evidence levels.

The [application target matrix](../adr/0249-qualify-calendar-occurrences-and-reminders-by-firmware.md)
records the implemented authoring and projection subset. Basic editing includes
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

Nano 6 / 1.2, Nano 7 / 1.0.4 and Nano 7 / 1.1.2 explicitly register
`iCalendarsSupported=0`. Retained Calendar strings do not qualify a Calendar
workflow on those targets. Clock Alarms are separate.

Nano 2 updater families 19/29 share encrypted firmware 1.1.3. The lab currently
has no accepted plaintext OSOS or decompilation for that image. Its native
Calendar behavior remains unknown, rather than unsupported. This work does not
stage a loader or resume the separate physical acquisition procedure.

Monthly/yearly construction, BY* filters, recurrence exceptions, all-day and
multi-day repetition, and timezone transition evaluation have richer native
paths than the currently qualified daily/weekly subset. Their presence is not a
complete behavioral specification, and they remain preserved without speculative
authoring or occurrence expansion. This coverage work must not be described as
complete support for every Calendar feature present in firmware.

To Do status is not a Host progress tracker. Inspected native consumers recognize
COMPLETED, IN-PROCESS and CANCELLED, and fresh objects default to incomplete.
The application completes a native To Do with `STATUS:COMPLETED` and reopens it
by removing STATUS and the old completion timestamp. It does not manufacture
completion timestamps or percentage changes. Imported unrelated properties remain
preserved. The byte-only codec's unqualified compatibility mode retains its
existing explicit Host metadata behavior; mounted workflows supply exact profiles.

Saved reminders describe persisted TRIGGER bytes. They do not establish live
adoption, notification delivery, sound selection or hardware wake behavior.
