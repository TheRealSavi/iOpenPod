# ADR-0247: Manage Extras through qualified lossless file edits

- Status: Accepted
- Date: 2026-11-07
- Extends: ADR-0234, ADR-0240, ADR-0242 and ADR-0243

ADR-0251 updates Calendar availability and editing. This record continues to
govern Clock Alarm qualification and the Extras publication workflow.

## Context and decision

The requested Calendar/To Do and Alarms/Sleep Timer pages operate on different
firmware artifacts. A native application being present does not prove a remote
control protocol, a writable record layout or an exact UTC interpretation. The
[firmware investigation](../research/calendar-alarm-firmware-2026-11-06.md)
qualifies useful saved fields while leaving new Alarm defaults, some record
meanings, timezone evaluation and physical wake behavior unresolved.

Compact navigation groups Calendar and Alarms under **Extras** using the shared
dropdown. Sidebar navigation lists the two pages directly. Native Extras
capabilities belong to Device Registry. Strongest-authority model, RetailOS and
updater-family evidence separately qualify application writes; unknown evidence
permits inspection without guessing a writer. The latest studied targets are
Mini 2 / 1.4.1, Video 5/5.5 / 1.3, and Classic families 24 / 1.1.2, 33 / 2.0.1,
35 / 2.0.4 and 38 / 2.0.5. The later two require their updater-family evidence.

iPodDB owns bounded Calendar parsing/authoring and existing Alarm codecs. It
retains original bytes, unknown properties and components. Calendar values use
Whenever `Date`, `PlainDateTime` or `Instant`, with a separately retained TZID
and original text. Imported zones never resolve implicitly against the Host;
recurrence rules are retained rather than expanded speculatively. Basic
iCalendar 2.0 events and To Dos can be created, edited and removed. Imports keep
the selected `.ics`/`.vcs` bytes. Legacy encodings, ambiguous fields and complex
timing restrict the relevant edits without blocking other files or Library work.

Classic existing alarms expose their 1970 civil calendar coordinate and repeat
mode. Mini 2 exposes the minute-of-day word in exact qualified Preferences
framing. Video exposes that word as a read-only Clock Alarm Projection. Writers
patch only proven fields and preserve all other bytes. The
workflow does not invent new alarm defaults, enable/sound values or a mapping
from an unknown saved control to a UI label. Existing Alarm editing is separate
from Calendar reminders and their retained VALARM components.

**November 7 evidence correction:** the [whole-file Video investigation](../research/preferences-video-complete-2026-11-07.md)
shows that individual per-city alarms load from `iPod_Control/Device/clock`.
The collection computes its earliest alarm and copies it into Preferences;
changing that projected minute word does not edit a persistent selected Clock
Alarm. Native record construction/import on all three latest Video inputs
confirms the distinction. The earlier raw byte-patch proof remains valid, but
it does not qualify this user workflow. Device Registry therefore keeps Video
Calendar editing enabled and marks Video alarm authoring unavailable. The Alarms
page labels its captured value as a Clock alarm snapshot and explains that this
read-only saved time may be disabled or out of date. Unknown times remain
nonblocking observations. A future per-city editor
requires its own lossless `clock` record contract and coupled persistence model.

Sleep Timer native support is displayed with device-specific on-device guidance.
No qualified mounted-file command currently starts/stops it. Do not substitute a
Host countdown or imply that changing an Alarm file arms a running hardware timer.
Physical wake and sound acceptance remain outstanding.

## Calendar identity and naming, 2026-11-08

The [naming investigation](../research/calendar-names-and-groups-2026-11-08.md)
identifies Classic 2.0.1's `X-WR-CALNAME` dispatch and named collection selection.
The application retains Calendar identity separately from Calendar Entries,
including empty calendars. Files with the same exact saved name form one group;
unnamed calendars remain distinct from a calendar literally named Other. No
case-folding or Unicode normalization is inferred for native identity.

The Calendar page offers All calendars and individual calendars, creation,
renaming, named imports and destination selection for new entries. File paths
remain source identities and never derive from display names. A new entry with
no destination uses a named iOpenPod calendar, reusing its captured file when
available. Explicit creation and rename reject collisions with another name.

Name editing is qualified for a single editable iCalendar 2.0 container with at
most one plain `X-WR-CALNAME` property. The writer replaces only that property's
span, or inserts it before entries, retaining all other bytes. Multiple containers,
duplicate name properties and legacy formats remain readable without name edits.
Import without a name retains every byte; explicitly naming an import changes
only name metadata. Empty complete calendars can be imported.

Renaming an exact-name group prepares all captured member files in one Storage
Transaction, with a source fingerprint on every replacement. Any stale member
rejects the operation before publication. Device changes invalidate dialogs and
destination choices. These additions do not establish native case-comparison
rules or physical-device acceptance beyond the research evidence.

## Publication and lifecycle

The Application Layer captures Extras through Storage on a worker thread. An
explicit edit reserves the Active iPod, verifies the issued catalog and current
firmware evidence, and publishes one source-fingerprinted Storage Transaction.
Storage stages, verifies, commits and retains recovery on interruption. The result
is reread before presentation. Calendar imports use bounded Host capture and
generated device-relative destinations; GUI code never opens device paths.

Device changes invalidate page state and stale dialogs. Disconnects cancel work;
only an actual transaction recovery condition gates subsequent device writes.
Optional parsing and datetime issues remain local to Extras. Merely opening a
page never writes, and these artifacts do not become Library or Sync dependencies.

## Validation

Codec tests cover byte preservation, invalid dates, folds/gaps without Host-zone
conversion, unknown fields, Calendar edits, Alarm scalar patches and exact
Preferences framing. Virtual Storage tests exercise publication, imported-byte
preservation, external changes and stale catalog rejection. GUI tests cover both
navigation styles, capability visibility and edit lifecycle. Physical firmware
acceptance remains separate from these tests and the earlier ARM probes.
