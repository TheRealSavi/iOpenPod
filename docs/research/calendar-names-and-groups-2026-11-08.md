# Calendar names, multiple calendars and the Other group

Investigated 2026-11-08. This follows the
[Calendar/Alarm investigation](calendar-alarm-firmware-2026-11-06.md).
The reported symptom is an iPod showing one Calendar group named Other.
This investigation changes documentation only; it does not qualify a new writer.

## Findings

Multiple calendars are a supported device concept. Apple's Classic 120GB manual,
page 54, describes syncing all calendars or selected calendars. Page 55 describes
copying calendar files into `Calendars`; it does not prescribe one subdirectory
per named calendar. [Apple manual][manual]

For Classic updater 33 / RetailOS 2.0.1, the native parser recognizes
`X-WR-CALNAME` and selects a Calendar object by its value. Distinct names can
select distinct Calendar objects; a lookup hit reuses an existing object.
Calendar identity therefore cannot be modeled merely as a filename or event
title. Native evidence is detailed below.

iOpenPod currently has two gaps:

1. New entries each produce a fresh UUID-named `.ics` file whose `VCALENDAR`
   contains VERSION and PRODID, but no `X-WR-CALNAME`. An event's SUMMARY names
   the event, not its calendar. See [authoring][authoring] and
   [new-entry publication][publication].
2. Inspection already reads multiple direct `.ics`/`.vcs` files, but projects
   only their events into a flat tuple of `CalendarItem(document_key, entry)`.
   The page has no named calendar collection or calendar selector. Empty
   calendars contribute no rows. See [capture][capture], [models][models] and
   [presentation][presentation].

Missing calendar-name metadata is consistent with the reported Other group.
The exact localized fallback string and its missing-versus-empty-name branch
were not independently established in this pass. Do not describe Other as a
one-calendar device limit or claim that this investigation executed that UI.

## Native naming evidence

The strongest inspected target is Classic updater 33 / RetailOS 2.0.1, original
OSOS SHA-256
`220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
Addresses below are runtime addresses, not disk-format offsets.

- The Calendar property dispatcher at `0x08149ef8` tests the token-table entry
  at offset `+0xd0`, `x-wr-calname`, and routes it to `0x0814a24c`. The
  [existing receipt][receipt] retains this token table. The dispatcher is an
  unowned ARM body in the existing Ghidra project; the
  [raw export][dispatch] is evidence, not an assertion of a Ghidra function.
- The handler at `0x0814a24c` decodes/copies text into the parser's retained name
  at `+0x7c`, then calls the selection helper. [Handler export][handler]
- The helper at `0x0814a1e4` obtains that name and calls collection lookup
  `0x08271f9c`. A miss allocates a `0x90`-byte object, constructs it with the
  name through `0x0825cf68`, and inserts it through `0x081061f4`. The selected
  object is cached at parser `+0x74`. A lookup hit avoids creating a second
  object. [Selection export][selection]
- The event path at `0x08149e84` uses the same selection helper before adding an
  event to the selected Calendar object. These are parser/object relationships;
  they do not authorize persisting those runtime structures.

The exports include decompiler-inferred types and research symbol names. They
are supporting navigation rather than original Apple source. The investigation
also inspected original ARM instructions. Exact comparison behavior, including
case, whitespace and Unicode normalization, was not qualified. Do not merge
calendar names case-insensitively based on this finding.

The earlier receipt includes `x-wr-calname` in all four latest Classic token
tables. Token presence alone does not prove identical grouping, fallback or
string-comparison behavior for those other Classic targets, Mini or Video.
No new whole-file ARM import or physical-device acceptance test was run.

## Application reproduction

Two small checks exercised the current public interfaces:

- Creating Work and Personal events with `create_calendar`, each with an
  explicit start date, produced no `X-WR-CALNAME` property in either document.
  An assertion that both generated calendars have names failed with
  `Both generated Calendar files lack X-WR-CALNAME`.
- A Virtual Storage volume containing `Calendars/Work.ics` and
  `Calendars/Personal.ics`, each with its own `X-WR-CALNAME` and one event,
  returned two captured files and two events through `read_extras`. Neither
  projected item exposed a calendar name. This rules out a one-file capture
  limit for this minimal case. Both files remained unmodified.

Imported source bytes retain their name properties, even though the application
does not expose them as a typed calendar identity. Multiple VCALENDAR roots in
one file are also readable, with edits deliberately disabled: the existing
`test_multiple_calendars_can_be_inspected_but_are_not_rewritten_as_one` covers
that separate preservation case. [Codec tests][tests]

The device-compatible metadata to investigate for named authoring is, for example:

```text
BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:Work
...
END:VCALENDAR
```

The later standardized calendar-level `NAME` property is defined by RFC 7986
(2016). Its existence does not establish support in these older firmwares or
make it a replacement for the observed `X-WR-CALNAME` dispatch. [RFC 7986][rfc]

## Implementation implications

An implementation should preserve calendar containers and their names separately
from Calendar Entries, including empty named calendars and document/component
source identity. The page can then expose all entries or a selected calendar,
and new-entry intents can identify the destination calendar. File paths remain
Storage preconditions; display names must not become paths or unique identities.

Name authoring, escaping, duplicate-name policy, malformed/duplicate properties
and default-calendar behavior need explicit decisions and regression fixtures.
Imported bytes must retain existing metadata. A simple filename change or event
SUMMARY edit cannot address the missing calendar identity. Existing unnamed
files should not be silently regrouped or renamed as part of unrelated edits.

[manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf
[rfc]: https://www.rfc-editor.org/rfc/rfc7986.html#section-5.1
[authoring]: ../../src/iPodDB/calendar/codec.py
[publication]: ../../src/iOpenPod/app/services/extras.py
[capture]: ../../src/iOpenPod/app/services/extras.py
[models]: ../../src/iOpenPod/app/models/extras.py
[presentation]: ../../src/iOpenPod/GUI/pages/calendar_page.py
[tests]: ../../tests/iPodDB/test_calendar.py
[receipt]: ../../../ipod-firmware-lab/artifacts/classic-calendar-native-20261106-v6/receipt.json
[dispatch]: ../../../ipod-firmware-lab/artifacts/classic-calendar-parser-20261106-v5/08149ef8-unowned-context.txt
[handler]: ../../../ipod-firmware-lab/artifacts/preferences-classic33-full-export-20261107/0814a24c.c
[selection]: ../../../ipod-firmware-lab/artifacts/preferences-classic33-full-export-20261107/0814a1e4.c
