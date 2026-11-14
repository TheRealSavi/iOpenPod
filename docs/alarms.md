# Alarms

iOpenPod manages saved Clock Alarms through **Extras → Alarms** in compact
navigation and **Alarms** in the sidebar. Exact firmware evidence qualifies
editing independently of native feature availability. Nano 2 uses the explicit
compatibility policy documented below. Merely opening this page
does not write to the device. The page shows saved Clock Alarms directly, without
internal tabs. Nano 6/7 have no Alarms route or Countdown Timer support in iOpenPod.

## Firmware coverage

The November 13, 2026 investigation inventories all **20 updater-package
identities in 17 workspaces** in the local firmware lab. Eighteen have inspectable
firmware; both Nano 2 packages have encrypted OSOS. This is coverage of the
available latest-release corpus, not every historical iPod firmware release.
Earlier full-size iPods have no images in this corpus and gain no guessed writer.

| Models | Release / updater families | Saved format | iOpenPod controls |
| --- | --- | --- | --- |
| Mini 1 | 1.4.1 / 3, 6 | Binary Preferences | Time, disable, qualified enable, Beep and source-qualified Playlists |
| Mini 2 | 1.4.1 / 7 | Binary Preferences | Time, disable, qualified enable, Beep and source-qualified Playlists |
| Nano 1 | 1.3.1 / 14, 17 | Per-city `Device/clock` | Add/remove cities; time, manual DST, enable, Beep and Playlists |
| Video 5/5.5 | 1.3 / 13, 20, 25 | Per-city `Device/clock` | Add/remove cities; time, manual DST, enable, Beep and Playlists |
| Nano 2 | 1.1.3 / 19, 29 | Assumed Nano 1 `Device/clock` compatibility | Same city controls by user direction; native implementation unverified |
| Nano 3 | 1.1.3 / 26 | Dated `Device/alarms` | Create/remove; date/time, repeat, label, enable, tones and Playlists |
| Nano 4 | 1.0.4 / 31 | Dated `Device/alarms` | Create/remove; date/time, repeat, label, enable, tones and Playlists |
| Nano 5 | 1.0.2 / 34 | Dated `Device/alarms` | Create/remove; date/time, repeat, label, enable, tones and SQLite Playlists |
| Classic 6 | 1.1.2 / 24 | Dated `Device/alarms` | Create/remove; date/time, repeat, label, enable, tones and Playlists |
| Classic 120 GB | 2.0.1 / 33 | Dated `Device/alarms` | Create/remove; date/time, repeat, label, enable, tones and Playlists |
| Classic 7 | 2.0.4 / 35; 2.0.5 / 38 | Dated `Device/alarms` | Create/remove; date/time, repeat, label, enable, tones and Playlists |
| Nano 6 | 1.2 / 36 | Device-only Countdown Timer | None |
| Nano 7 / refresh | 1.0.4 / 37; 1.1.2 / 39 | Device-only Countdown Timer | None |

Strongest-authority RetailOS and updater-family evidence selects the format.
Contradictory or missing required evidence leaves editing unavailable. A matching
file alone never identifies a device. Nano 2's Clock app is corroborated by
Apple's guide; that does not establish its encrypted implementation's file format.
By explicit user direction, [ADR-0261](adr/0261-use-nano-1-alarm-compatibility-for-nano-2.md)
uses Nano 1's codec and Playlist projection for Nano 2 1.1.3. Existing files must
still pass the codec's structural checks. This compatibility assumption is kept
separate from independently executed firmware evidence and does not enable Nano 2
Preferences editing.

## Saved alarm behavior

Dated alarms have a native civil date/time, seven repeat modes and 23 predefined
labels. The editor offers Once, Daily, Weekdays, Weekends, Weekly, Monthly and
Yearly. Labels run from Wake up through Party; the native default is Alarm.
Unknown repeat and label values stay unchanged until explicitly replaced.
The firmware's sound-name string is separate from the label menu index.

[Native lifecycle probes](research/alarm-recurrence-lifecycle-2026-11-13.md)
independently verify recurrence vectors and nine-minute snooze in all seven
dated-alarm images. Snooze's runtime override is not saved. Monthly recurrence
uses an unsaved original-day anchor, so a previously clamped saved date alone
cannot establish an exact future monthly schedule. Physical reload behavior
remains separate from these bounded instruction probes. iOpenPod writes the native
saved date and repeat fields without repairing firmware recurrence behavior or
introducing a separate monthly-day field.

New dated alarms use independently executed native constructor defaults, with
the user's chosen date/time, repeat, label, enable state and verified sound. The
constructor's empty tone string is not an audible default without a selected
Playlist. Removing an alarm
removes only its complete record span. An absent file can be created; a malformed
or ambiguous file is never replaced with invented defaults. Unchanged sound fields
remain byte-preserved.

Mini stores minutes after midnight. Its enable transition can consult the native
Playlist ordering. A zero ID or an ID found in the captured native Library qualifies
enable editing; a nonzero unresolved ID does not imply that the native dynamic
On-The-Go tail lacks it. Disabling a recognized enabled mode needs no lookup.
Per-city Nano 1 and Video alarms use the selected city's minute coordinate and
stored sound selector; their native toggle has a different encoding from Classic.
The page names known cities and offers a searchable native catalog of 204 cities,
with manual daylight saving time. Each saved city owns one daily Alarm. **Add
city** creates the native city record and applies the chosen time, sound and
enable state; **Remove city** removes that city and its Alarm. Duplicate cities
and removal of the final city are supported. Missing and empty files accept
explicit creation; opening an empty store does not fabricate California, which
the firmware adds during its own initialization. Unknown city identifiers remain
preserved and display their retained Clock number.

The [city authoring investigation](research/alarm-legacy-city-authoring-2026-11-13.md)
verifies 1,150 native cases across the five Nano 1/Video inputs. The standalone
fixture includes all 204 exact city records. The
[city scheduling investigation](research/alarm-legacy-scheduling-cities-2026-11-13.md)
documents the native offsets and manual DST without substituting Host timezone
rules. Nano 2 uses this same flow under the user's compatibility direction.

## Sound persistence and selection

These settings are persisted, not RAM-only:

| Firmware family | Persisted sound and enable state |
| --- | --- |
| Mini | `iPod_Control/Device/Preferences`: mode bits at `0xb18`, u64 Playlist ID at `0xb24` (low word first) |
| Video / Nano 1 | `iPod_Control/Device/clock`: per-city current kind (tag 7), selected sound mode (tag `0x1f`), signed Playlist index (tag 8) |
| Classic / Nano 3–5 | `iPod_Control/Device/alarms`: control word (tag 7), Playlist selector (tag 8), tone name (tag `0x3c`) |

Mini Beep selection writes the Master Playlist ID and mode 0. Video/Nano 1 Beep
writes mode 0 and selector -1; Playlist selection writes mode 4 and a positive
native index. The native sound setter enables first; an explicit disabled checkbox
is applied afterward. Accessory Radio mode 12 is observed and retained, but not
offered without live accessory evidence.

`IPodLibrary.alarm_playlists` derives Mini, Nano 1 and Video arrays from retained
database records. The first type-2/3 dataset wins; native podcast, media, Smart
Playlist, empty-Playlist and imported-member rules differ by family. Sidebar order
and semantic snapshot ordering cannot substitute for this projection.

Classic/Nano 3–5 load tones from `iPod_Control/Tones`. The selected string is the
first line inside a tone file, not its filename. Beep is first and uses the native
localized resource name, resolved from qualified saved language settings. The app
offers custom names only when the candidate collection fits the native 19-custom
limit and names are valid, unique and distinct from the default. It never rewrites
tone files during Alarm edits. Unknown language or ambiguous tone sources do not authorize guesses.
The Sound dropdown offers a single tone or Playlist. Explicitly selecting a tone
clears the Playlist selector; explicitly selecting a Playlist clears the tone
string. Existing enabled gates are retained. Native combined tone/Playlist states
stay intact during unrelated edits and appear as a saved combined sound.

### Tones and Track conversion

Classic and Nano 3–5 have a **Tones** page under Extras (a direct route in Sidebar).
It lists saved names, durations and the built-in Beep. **Listen** previews the
saved note sequence on the computer; the iPod speaker has a different timbre.
Nano 6/7's 25 fixed Countdown Timer sounds do not use this custom-tone format.

Right-click one saved music Track and choose **Convert to tone…**. iOpenPod scans
the song locally for a repeated, active phrase, follows harmonic pitch evidence
over time, and arranges roughly seven seconds of notes and rests. Listen to the
result, edit its name if desired, then choose **Save tone**. The new tone becomes
available in the alarm's Sound menu. Conversion does not change the original
Track, create another Library Track, or change an existing Alarm's sound.

The arrangement uses existing audio-analysis libraries; no model download or
audio upload is needed. The main melody is not always unambiguous in dense music.
Silence and unpitched input can be rejected instead of producing arbitrary notes.
Tracks must be saved Music Tracks between one second and 15 minutes, and their
encoded files must not exceed 512 MiB. Analysis is cancellable. Native capacity
is 19 custom tones beside Beep; unique names and captured device sources are
checked when saving.

See [tone authoring evidence](research/alarm-tone-authoring-2026-11-13.md),
[melody extraction research](research/alarm-tone-melody-extraction-2026-11-13.md)
and [ADR-0265](adr/0265-author-alarm-tones-from-local-melody-arrangements.md).

### Playlist sources

Classic and Nano 3/4 Playlist choices use the
[native imported-array projection](research/alarm-playlist-source-projection-2026-11-13.md):
the first type-2/3 dataset, native membership and Smart attachment rules, native
UTF-16 title composition, the 255-unit name cache and Apple's mode-`0x1b`
comparator. The Master occupies raw index zero but is omitted from the picker;
saved selectors subtract one. Late Classic uses a wider media mask and excludes
two additional distinguished collections. Equal native names keep import order.
Native generated collections beyond the captured prefix are not guessed.

Nano 5 uses the [SQLite projection](research/alarm-playlist-nano5-sql-2026-11-13.md).
Its eligible saved containers follow `name_order`, with an eligible primary
container moved first. Selectors are zero-based. A saved On-The-Go Playlist stays
selectable: the excluded temporary On-The-Go row is separately generated at
runtime. Both captured SQLite companions bind explicit choices.

Unqualified records do not produce guessed selectors. In particular, binary
encoding-2 titles and empty composition-enabled titles can copy undefined native
scratch state; tied Nano 5 sort positions between selectable non-primary rows
have no proven ordering. These cases disable new Playlist choices while keeping
existing Alarm bytes intact and other qualified controls available. Ordinary
unique-order UTF-16 and SQLite libraries are supported.

Library saves leave Alarm selections unchanged for every model. If a Playlist
moves to a different native position or is deleted, the iPod uses the saved
selection as it normally would. iOpenPod neither updates that selection nor
blocks the Library save. This is the explicit user-directed policy in
[ADR-0262](adr/0262-leave-alarm-selections-unchanged-during-library-writes.md).
Source checks still apply when the user explicitly edits an Alarm sound.

The time editor never applies the Host timezone. Dated alarm words use the 1970
civil epoch, not the media database's 1904 epoch. Native unknown/sentinel values
survive unrelated edits. The page does not calculate a purported next firing
time from the Host clock, DST rules or a recurrence approximation.

## Device-only timers

Countdown Timer on Nano 6/7 and Sleep Timer remain device-only features.
iOpenPod has no timer page, saved-preset editor, dedicated timer inspection or
start/stop commands. Nano 6/7 do not expose the Alarms route. See
[ADR-0267](adr/0267-remove-nano-countdown-timer-support.md).

The historical firmware investigations below remain available as research.
Ordinary Preferences edits preserve unrelated timer values as Unknown Data;
the separate Nano 6 timer file is not accessed.

## Publication and safety

The existing Extras worker captures bounded files through Storage. Each explicit
edit rechecks the issued catalog, Active iPod, Filesystem Session and firmware
evidence. A source fingerprint protects replacements; an absence precondition
protects new files. Storage stages, verifies, journals and publishes the change.
Creation/removal receives the same firmware checks as field edits. The result is
reread before presentation. Device changes close stale editors and stop work.
Playlist choices bind to the captured binary Library fingerprint or both Nano 5
SQLite companion fingerprints; tone choices bind to
the saved language, tone file fingerprints and a rechecked directory inventory.

Publication changes saved files. It does not prove that currently running firmware
has adopted them: an in-memory owner can later save its own state. Check the alarm
and sound on the iPod after ejecting. Native instruction probes establish the
documented format/control behavior; physical wake, sound delivery and live reload
still require device acceptance testing. No physical iPod was changed in this work.

## Evidence and implementation

- [Mini, Video and Nano 1/2 research](research/alarms-legacy-firmware-2026-11-13.md)
  includes exact image identities and 52 new native cases.
- [Classic and Nano 3–5 research](research/alarms-clickwheel-firmware-2026-11-13.md)
  includes native records, constructors, toggles, label tables and repeat evidence.
- [Touch Nano research](research/alarms-touch-firmware-2026-11-13.md)
  includes the full inventory, native lifecycle traces and Apple user guides.
- [Legacy sound research](research/alarm-sounds-legacy-2026-11-13.md)
  adds 80 native sound, toggle, array and reload probes.
- [Click-wheel sound research](research/alarm-sounds-clickwheel-2026-11-13.md)
  adds 113 native parser/locale executions, localized default names and collation limits.
- [Touch timer controls](research/timer-controls-touch-2026-11-13.md)
  adds 135 native executions, 25 sound identities and initialization adoption.
- [Legacy scheduling and cities](research/alarm-legacy-scheduling-cities-2026-11-13.md)
  adds 1,098 native cases, exact city mappings and Nano 1 creation/Radio state.
- [Dated alarm recurrence and lifecycle](research/alarm-recurrence-lifecycle-2026-11-13.md)
  adds 223 native cases across all seven images, including Nano 4/5 arithmetic,
  monthly-anchor persistence limits and nine-minute snooze.
- [Playlist ordering](research/alarm-playlist-ordering-2026-11-13.md)
  adds 4,131 native cases, all seven comparators, the Smart-leaf filter and
  Classic 2.0.1's generated suffix/final On-The-Go lifecycle.
- [Playlist source projection](research/alarm-playlist-source-projection-2026-11-13.md)
  closes the binary import, composition and variant filtering contract with
  12,517 additional native cases and standalone name fixtures.
- [Nano 5 SQLite Playlists](research/alarm-playlist-nano5-sql-2026-11-13.md)
  adds 250 native cases and three captured-library comparisons.
- [City authoring](research/alarm-legacy-city-authoring-2026-11-13.md)
  adds 1,150 native cases and standalone records for all 204 cities.
- [Touch timer reload and delivery](research/timer-reload-and-delivery-2026-11-13.md)
  adds 167 native cases, retained-save/USB lifecycle traces and delivery guards.
- [ADR-0259](adr/0259-manage-native-alarm-collections-and-countdown-observations.md)
  records the boundary and publication decisions.
- [ADR-0260](adr/0260-bind-alarm-sounds-to-native-sources-and-preserve-playlist-identities.md)
  extends that contract with source-qualified sound edits. Its timer support is
  superseded by [ADR-0267](adr/0267-remove-nano-countdown-timer-support.md).
- [ADR-0263](adr/0263-author-clock-cities-and-native-alarm-playlist-selections.md)
  includes city authoring and the binary/SQLite Playlist selection flows.

The Original iOpenPod checkout at commit
`6290e4da66a71cb22b8abfac9a4defbe61f96e29` was searched for alarm/Sleep Timer
code and documentation; it provides no matching implementation baseline.
The preexisting 2.0 Extras workflow and earlier firmware research are extended.
All committed format vectors are standalone; the application and tests do not
load the sibling lab or proprietary firmware.

Codec tests cover native vectors, unknown-byte preservation, malformed and
ambiguous sources, control transitions and explicit authoring. Virtual Storage
tests cover missing-file creation, stale source rejection, removal and separation
from Preferences projections. GUI tests cover native field choices, saved
Alarm editing and stale editor/device lifecycle. Hallmark refinement uses the existing
semantic palettes, typography, controls and keyboard model, with rendered
light/dark and narrow/wide verification.
