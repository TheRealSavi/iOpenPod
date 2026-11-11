# ADR-0249: Qualify Calendar occurrences and reminders by firmware

- Status: Superseded by ADR-0251
- Date: 2026-11-08
- Extends: ADR-0247 and ADR-0243

## Context

Recurrence tokens and reminder constructors do not establish complete Calendar
behavior. The user requires firmware-backed behavior with explicit target
differences. The initial Mini 2 recurrence and Classic reminder experiments are
extended by the [lab-wide coverage investigation](../research/calendar-firmware-coverage-2026-11-08.md).
Exact-image experiments qualify each additional profile independently. A generic RFC
recurrence engine or an invented alarm action would exceed that evidence.

## Decision

Device Registry carries the exact qualified firmware identity in Extras support.
The Application Layer composes it with an explicit byte-only Calendar profile.
Unknown targets retain imported data without obtaining these new edit rights.
iPodDB owns native qualification checks, bounded occurrence projection and
lossless property/trigger patches. GUI code submits typed series/reminder intents;
publication retains the existing source-checked Storage workflow.

| Target | Recurrence display and editing | Calendar Reminder editing |
| --- | --- | --- |
| Mini 1 / updaters 3, 6 / 1.4.1 | Qualified subset below | Qualified subset below |
| Mini 2 / updater 7 / 1.4.1 | Qualified subset below | Qualified subset below |
| Nano 1 / updaters 14, 17 / 1.3.1 | Qualified subset below | Qualified subset below |
| Nano 3 / updater 26 / 1.1.3 | Qualified subset below | Qualified subset below |
| Nano 4 / updater 31 / 1.0.4 | Qualified subset below | Qualified subset below |
| Nano 5 / updater 34 / 1.0.2 | Qualified subset below | Qualified subset below |
| Video / updaters 13, 20, 25 / 1.3 | Qualified subset below | Qualified subset below |
| Classic / updater 24 / 1.1.2 | Qualified subset below | Qualified subset below |
| Classic / updater 33 / 2.0.1 | Qualified subset below | Qualified subset below |
| Classic / updater 35 / 2.0.4 | Qualified subset below | Qualified subset below |
| Classic / updater 38 / 2.0.5 | Qualified subset below | Qualified subset below |
| Nano 6 / 1.2, Nano 7 / 1.0.4 and 1.1.2 | Native Calendar unsupported | Native Calendar unsupported |
| Nano 2 / updaters 19, 29 / 1.1.3 | Unknown: encrypted firmware only | Unknown: encrypted firmware only |
| Other targets | Saved dates only; recurrence preserved | Preserved, read-only |

### Qualified occurrence subset

Only same-day, whole-second floating VEVENT start/end pairs before year 3000,
with DAILY or WEEKLY RRULEs, positive intervals, and either COUNT or a floating
UNTIL are qualified. COUNT and UNTIL together remain unsupported. No BY*, WKST,
RDATE, EXDATE, EXRULE or RECURRENCE-ID handling is inferred. All-day, zoned,
multi-day, monthly and yearly series remain preserved without expansion.

The seed is included, candidates before it are excluded, weekly membership
retains its weekday, and UNTIL includes a start at the exact boundary. Native
COUNT initialization scans at most 10,000 candidate days; the last generated
start must be fewer than 10,000 days after the seed. A missing native UNTIL has
a year-3000 bound, rather than infinity. The app conservatively confines its
qualified series and projection to dates before 3000. Authoring intervals are
bounded to 1..1000, and occurrence queries span at most 63 days; these are
application resource/input bounds, not additional firmware features.

The month grid and selected-day agenda show qualified occurrences for their
visible date window. All saved entries lists each source series once. Occurrences
retain their Calendar Entry's source identity; edit and remove actions explicitly
affect the whole series. There is no individual-occurrence editor or detached
exception authoring. Unknown patterns show their saved dates with an explanation.

### Qualified saved-reminder subset

The supported targets independently qualify a single nested VALARM with one relative
TRIGGER. The initial editor authors only reminders zero to 10,080 minutes before
the floating event start. This one-week bound is an application input limit.
The native start anchor is the default; new components contain TRIGGER only.
No ACTION, sound, repeat count or delivery mode is invented.

Existing eligible trigger edits preserve all other component bytes, including
unknown properties. Removing an explicitly selected supported reminder removes
that component. Absolute, end-relative, subminute, positive/after-start,
ambiguous and multiple reminders remain read-only. Related parameter and absolute
trigger observations remain visible even where they do not qualify editing.

Successful publication proves saved bytes. It does not prove live firmware
adoption, hardware arming, sound or physical notification delivery. Clock Alarms
and Sleep Timer remain separate workflows. Each additional target has its own
constructor, property-dispatch and relative-trigger evidence; matching strings
alone do not grant authoring rights.

## Evidence and validation

- [Mini recurrence qualification](../research/calendar-recurrence-qualification-2026-11-08.md):
  720 native candidate-membership checks, including returned spans, leap-day/year
  crossings, COUNT and UNTIL boundaries, with exact image and memory-map hashes.
- [Classic reminder qualification](../research/calendar-reminder-qualification-2026-11-08.md):
  28 new per-image constructor/dispatcher cases plus the earlier independently
  executed duration and start/end parameter probes.
- Authored codec tests translate these results into firmware-specific fixtures;
  unsupported targets, patterns and trigger shapes retain bytes and reject edits.
- Virtual Storage and GUI tests cover profile composition, publication, projected
  dates, series identity and target-specific controls. Firmware/emulation tooling
  remains a research dependency only. Physical acceptance remains separate.
