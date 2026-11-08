# Auxiliary files containing date and time information

Research date: **2026-11-06**. This is a read-only inventory of existing source,
qualified firmware research, retained capture reports, and Apple's Classic
manual. It adds no hardware observations or native probes. Exact Classic
24/1.1.2, 33/2.0.1, 35/2.0.4, and 38/2.0.5 parity is stated only where existing
evidence establishes it; ordinary format support is not an all-four firmware proof.

**November 7 supplement:** the [whole-file Preferences investigation](preferences-complete-inventory-2026-11-07.md)
adds independently traced Video Clock storage and later-Nano timer stores below.
Those new claims come from original firmware instructions and bounded probes;
they do not widen the earlier Classic claims by analogy.

## Photo Database and ArtworkDB

The two files share the MHII image-header layout. Offsets below are relative to
each `mhii` Chunk, not the beginning of the file. PhotosDB reuses the shared
typed header. [MHII definition][mhii], [PhotosDB definition][photo-mhii]

| File | Exact field | Meaning and interpretation |
| --- | --- | --- |
| `Photos/Photo Database` | MHII `+0x28`, little-endian u32, `original_date` | Original/creation date under the Host model. Current iOpenPod interprets it as local calendar seconds from 1904, then resolves a best-effort Unix instant using the captured Device Time Context. |
| Same | MHII `+0x2c`, little-endian u32, `exif_taken_date` | Photo taken/digitized date under the Host model, with the same conversion. It is a separate database word, not a direct view into the source image's EXIF bytes. |
| `iPod_Control/Artwork/ArtworkDB` | Same two MHII words | Same retained binary fields. Ordinary album artwork is not evidence that the values are populated or used as photo dates. |

Current Photo projection uses `project_mac`; new/changed values use
`unix_to_mac`; unchanged values retain their native words. Zero is the Host
missing-date sentinel. For a known fixed offset, the interpretation is
`Unix = native - 2082844800 - seconds_east_of_UTC`. This remains Host policy:
neither a fold marker nor past city selections are present in these words.
[Projection][photo-read], [writing][photo-write], [time contract][time]

Classic 33/2.0.1 provides direct firmware evidence that both paths reach importer
`0x0805e54c`, which copies MHII `+0x28` to native Image `+0x28`. The existing
research does not independently establish the date epoch, EXIF-field consumer,
every gallery use, or equivalent date consumers on the other three latest
targets. Its pinned image/hash and exact dataflow are retained in the
[firmware import report][image-import].

The older [PhotosDB format note][photo-format] describes **Original iOpenPod's
unsigned Unix output**. That historical producer behavior disagrees with current
Mac-date conversion and the later libgpod evidence recorded in the
[time reconciliation][reconciliation]. It must not be presented as the current
on-device interpretation or as settled Classic firmware semantics.

Nearby fields are not calendar dates: MHII `+0x24` is the verified unsigned
image-order key; MHNI `+0x24` is a playback-position image key; MHBA `+0x24`
and `+0x28` are slideshow/transition durations. Packed `.ithmb` data is raster
storage, with no calendar field established here. [Image ordering][ordering],
[MHNI][mhni], [MHBA][mhba]

## SQLite: distinguish the Classic Extras file from the later library set

The Classic catalog uses binary iTunesDB and does not select the full SQLite
Library Artifact Set. Nano 5/6/7 profiles do. Nevertheless, a qualified Classic
6.5/2.0.1 physical capture contains `iPod_Control/iTunes/Extras.itdb`, with
Genius tables, and no `Library.itdb` or separate `Genius.itdb`. Thus “Classics
never use SQLite” would be incorrect. No calendar timestamp is currently named
in those three Genius table schemas or decoded payload models. Unknown payload
bytes are retained. [Catalog][catalog], [Classic capture][genius-capture],
[Genius models][genius-models]

For the **later nano library set**, the containing directory is
`iPod_Control/iTunes/iTunes Library.itlp/`. SQLite fields are table/column
locations, not fixed byte offsets. The supported date mappings are:

| Artifact | Table columns | Meaning |
| --- | --- | --- |
| `Library.itdb` | `item.date_modified`, `item.date_released` | Track modification and release. |
| Same | `container.date_created`, `container.date_modified` | Playlist/container creation and modification. |
| Same | `podcast_info.date_released` | Episode release. |
| Same | `store_info.date_purchased`, `store_info.date_released` | Store purchase/release values in retained captures. The current generator does not invent a Store record from dates alone. |
| `Locations.itdb` | `location.date_created` | Track date added, not source-file modification. |
| `Dynamic.itdb` | `item_stats.date_played`, `item_stats.date_skipped` | Playback/skip history. |
| Same | `rental_info.rental_date_started`, `rental_info.rental_playback_date_started` | Named rental-date fields exist in the schema; this inventory does not establish their complete semantics or Classic applicability. |

Supported generated dates use UTC Core Data seconds: `value = Unix - 978307200`,
with zero retained as missing. The date-pair evidence is from nano 5/7 captures,
not a Classic timestamp specification. Rental date names alone do not prove that
same conversion. `Extras.itdb` chapter/lyrics tables have no named calendar
columns; chapter positions are media timing. `Locations.itdb.cbk` is a checksum
companion. No `.POD` equivalent date layout was established in the inspected
models/research. [Schema][schema], [writer][sqlite-write],
[artifact names][sqlite-artifacts], [paired captures][reconciliation]

## Calendars, Contacts, Notes, alarms, stopwatch, and recordings

Apple documents manual calendar/to-do import through `Calendars/*.ics` and
`Calendars/*.vcs`, contact import into `Contacts/`, and plain text in `Notes/`.
It also documents alarms with date/time/repeat settings, stopwatch logs with
session-start dates/times, and saved WAV voice memos listed by date/time.
These are product/file-family facts; the manual does not specify their private
binary offsets or timestamp epochs. [Classic manual, pages 50–56][manual]

For iCalendar text, the standard identifies `DTSTART`/`DTEND`, task `DUE`,
`DTSTAMP`, `CREATED`, `LAST-MODIFIED`, recurrence dates/rules, and alarm triggers.
Values may be date-only, UTC with `Z`, local with `TZID`, or floating local time.
They are not automatically Mac-epoch integers. The exact Classic-supported
property subset, recurrence/DST evaluation, and `.vcs` compatibility are not
traced here. [iCalendar specification][ical]

For a vCard-formatted contact, `BDAY` names a birthday and `REV` a revision
date/time under the format specification. This does not establish that the
Classic displays or consumes either field. Notes may contain dates as ordinary
text; no structured Notes calendar field is established. The new
[Calendar and Alarm investigation](calendar-alarm-firmware-2026-11-06.md)
qualifies Classic `iPod_Control/Device/alarms` token records and bounded repeat
logic on all four latest targets. It also separates Mini/Video Alarm Preferences,
imported Calendar reminders and hardware wake scheduling. Remaining stopwatch
storage paths and layouts, and the source of voice-memo display timestamps
(filename, filesystem metadata, or companion record), remain unmapped in this
inventory. [vCard specification][vcard]

## Video clocks and later-Nano timer stores

| Latest target | Artifact and exact locations | Meaning and interpretation |
| --- | --- | --- |
| Video 5/5.5 / 1.3, families 13/20/25 | `iPod_Control/Device/clock`; per-clock tags 2 (region), 3 (city), `0x14` (DST), 5 (nested alarm) | Variable tagged records, not fixed file offsets. Startup loads individual clocks/alarms here. The collection projects its earliest alarm into Preferences `0xB22` and associated fields; that projection is not a persistent per-city alarm editor. |
| Nano 6 / 1.2 | `iPod_Control/Device/iPodTimerSettings.xml`, `Timer.DateTime`, `Timer.SleepiPod`, `Timer.SoundIndex` | Running timer deadline is a separator-free local civil `YYYYMMDDhhmmss` string with no UTC/offset marker. SleepiPod distinguishes the sleep action; SoundIndex has registered bounds 0–24. |
| Nano 7 / 1.0.4 and refresh / 1.1.2 | Same Timer keys in `iPod_Control/Device/iPodSettings.xml` | Same observed deadline spelling and registration bounds, but a different containing store from Nano 6. Do not create a Nano 6 timer file on Nano 7 by analogy. |

Video's nested alarm container 5 stores LE u32 tag 6 as minutes in that city's
civil clock basis, tag 7 as alarm kind, and tags `0x1F` and 8 as separate retained
words whose full meanings remain incomplete. Kind 8 is the ordinary disabled
value. The one-byte city DST field has no alignment filler. The native record
reader/writer roundtrips 125-byte records; this does not qualify every malformed
full-file case. Preferences cannot establish the live selected city's enable
state: its saved projection and the current Clock collection have distinct
getters and predicates.

The [Video report](preferences-video-complete-2026-11-07.md) records constructor,
tagged import/export, startup and projection traces. The
[Nano 5/6/7 report](preferences-nano567-complete-2026-11-07.md) records exact
registration, path construction, timer formatting and reader behavior. Native
malformed-string handling, DST overlap/gap resolution and complete timer
clock-change rescheduling remain unresolved. Preserve unknown values and retain
nonblocking date estimates; none of these optional files is a Library dependency.

## Other scoped unknowns

The inspected game/authorization models do not establish a general calendar-date
layout for `Games_RO`, `GameData_RW`, `GameStats_WO`, or DSP settings. One positive
distinction is that Song Summoner's traced outside-game listening path compares
cumulative play counts and stored baselines; it does not consult per-play dates.
That is not evidence that all game files lack dates. [Game research][games]

This inventory is deliberately incomplete for private auxiliary formats. Filesystem
creation/modification times and timestamps embedded inside original media are
separate evidence from the database fields listed above. Their presence does not
establish that Classic firmware uses them, and none should become a blocking
calendar precondition for ordinary Library operations.

[mhii]: ../../src/iPodDB/ArtworkDB/shared/chunk_defs/mhii.py
[photo-mhii]: ../../src/iPodDB/PhotosDB/shared/chunk_defs/mhii.py
[photo-read]: ../../src/iPodDB/library/_photo_projection.py
[photo-write]: ../../src/iPodDB/library/_photo_writing.py
[time]: ../ipod-time.md
[image-import]: ../../../ipod-firmware-lab/notes/itunesdb/artwork-import-and-file-contract.md
[photo-format]: photosdb-format.md
[reconciliation]: ipod-time-reconciliation.md
[ordering]: mhii-image-field-followup.md
[mhni]: ../../src/iPodDB/ArtworkDB/shared/chunk_defs/mhni.py
[mhba]: ../../src/iPodDB/ArtworkDB/shared/chunk_defs/mhba.py
[catalog]: ../../src/device_registry/data/catalog.py
[genius-capture]: genius-generation-2026-10-24.md#classic-65g-physical-experiment-2026-10-24
[genius-models]: ../../src/iPodDB/genius/models.py
[schema]: ../../src/iPodDB/SQLiteDB/schema.py
[sqlite-write]: ../../src/iPodDB/SQLiteDB/database.py
[sqlite-artifacts]: ../../src/iPodDB/SQLiteDB/artifacts.py
[manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf
[ical]: https://www.rfc-editor.org/rfc/rfc2445
[vcard]: https://www.rfc-editor.org/rfc/rfc2426
[games]: unique-game-library-contracts.md#listening-outside-the-game
