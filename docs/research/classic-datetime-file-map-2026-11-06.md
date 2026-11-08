# Datetime files on the latest Classic targets

Scope: Classic 6 / 1.1.2, 6.5 / 2.0.1, 7 / 2.0.4 and 7.5 / 2.0.5. This map
separates byte definitions, qualified firmware consumers and Host interpretation
policy. It is not an exhaustive inventory of every private application file.
Binary offsets below are hexadecimal. A chunk offset starts at that chunk's
four-character marker, not at the beginning of the database file. Ordinary
Classic database words are little-endian; Smart rule operands are big-endian.

## File overview

| Path relative to the iPod root | Role and observed direction |
| --- | --- |
| `iPod_Control/Device/Preferences` | Firmware reads and persists city, Saved DST State and Saved Clock Correction. Host synchronization can indirectly change them. |
| `iPod_Control/Device/dst` | Optional annual DST rule input read by qualified 6.5/7/7.5 consumers; producer/write contract unknown. Classic 6 consumer unqualified. |
| `iPod_Control/Device/alarms` | Firmware reads/writes Alarm app entries in a variable-length token stream; scheduled scalar and repeat fields are independently qualified on all four latest targets. |
| `iPod_Control/iTunes/iTunesDB` | Host-authored Library metadata read by firmware: Track dates, Playlist fields and Smart rules. Playback updates are exported through sidecars. |
| `iPod_Control/iTunes/Play Counts` | Firmware writes pending playback changes; Host reads and reconciles them into the Library. |
| `Photos/Photo Database` | Host supplies photo metadata for device reading, including original/taken date fields. |
| `iPod_Control/Artwork/ArtworkDB` | Shared image-record date fields exist; exact use is less qualified than the Track playback dates. |
| `Calendars/*.ics`, `Calendars/*.vcs` | Host supplies appointments and to-do data for the iPod calendar application. |

Sources: [Preferences contract][preferences], [all-four support][support],
[sidecar codec][sidecars], [image definition][mhii], [Apple Classic guide][manual].
The new Alarm file evidence is detailed in the
[Calendar and Alarm follow-up](calendar-alarm-firmware-2026-11-06.md).

## Preferences: clock state rather than an absolute timestamp

All offsets in this table are **from file byte zero**. Do not add the four-byte
offset used when discussing the native RAM Preferences context.

| Offset | Encoding | Meaning |
| --- | --- | --- |
| `0xB6C` | u8 | Raw Saved DST State; separate writers use 0/1 or normally 0/60. |
| `0xB70` | little-endian u32 | Full numeric city ID, not an IANA name or UTC offset. |
| `0xB78` | little-endian i32 | Signed day component of Saved Clock Correction. |
| `0xB7C` | little-endian u32 | Raw seconds component of Saved Clock Correction. |

The exact file extent/version pairs are 2952/`0x3c`, 2956/`0x3d`, 2956/`0x3e`
and 2960/`0x3f`, respectively. The version word is at file offset zero.
Firmware uses software correction to obtain its adjusted calendar from the raw
hardware calendar. This correction is not a geographical timezone and must not
be added to recorded playback dates again. The saved file can lag live state
and queued notification handling. City selection can be automatic; zero and
`0x26` remain geographically unresolved in the qualified application profiles.
The DST byte is not a proven automatic-DST enable switch. [Definitions][pref-def],
[notification trace][notifications]

## DST file: annual selectors rather than event timestamps

There are 205 rows of 16 bytes. Row `i` starts at `prefix_size + 16*i`, using
zero-based indexing. Prefix size is zero on 6.5 / 2.0.1, and two on 7 / 2.0.4
and 7.5 / 2.0.5. The latter two bytes remain opaque, not a proved row count or
version. [Definition][dst-def], [firmware trace][dst-research]

| Row offset | Encoding | Meaning |
| --- | --- | --- |
| `0x00` | LE u16 | City ID |
| `0x02` | u8 | Enabled when nonzero |
| `0x03`, `0x04` | u8 each | Start/end weekday; Sunday is zero |
| `0x05..0x07` | 3 bytes | Retained unused bytes |
| `0x08`, `0x0A` | LE u16 each | Start month and week selector |
| `0x0C`, `0x0E` | LE u16 each | End month and week selector |

Months are nominally 1–12. On 6.5, week 4 means last; on 7/7.5, week 4 means
fourth and week 5 means last. Firmware supplies the transition-hour and
one-hour-adjustment behavior; those are not fields in the row. The file contains
no year, IANA timezone, historical rule series or event occurrence. Nominal rule
meaning also does not erase documented firmware weekday/February defects.
Compiled fallback rules and a saved custom file are distinct observations.
Classic 6's optional file remains opaque because its consumer is not qualified.

## iTunesDB: Track dates and their interpretation

Each Track has an `mhit` chunk. Its date fields are LE u32 words:

| Chunk offset | Field | Use and current interpretation |
| --- | --- | --- |
| `0x20` | `last_modified` | Track/file modification metadata; local Mac calendar word. |
| `0x58` | `last_played` | Most recent recorded play date; local Mac calendar word. |
| `0x68` | `date_added` | Library-added date and date-based selection; local Mac calendar word. |
| `0x8C` | `date_released` | Release metadata; Host/reference policy treats this as UTC Mac seconds. |
| `0xA0` | `last_skipped` | Most recent recorded skip date; local Mac calendar word. |
| `0xDC` | `date_added_to_itunes` | Added-to-iTunes/store-purchase-related metadata; Host/reference policy treats this as UTC Mac seconds. |

The four ordinary date import/event paths are qualified across all four latest
targets. The release/purchase field labels and UTC policy do not have equally
complete all-four firmware provenance. Header extent determines whether a field
is present. [Track definition][mhit], [time contract][time], [all-four support][support]

Here, a local Mac word encodes calendar seconds from 1904-01-01 without carrying
the event's timezone, DST occurrence or historical city. It is a local calendar
label, not a self-contained UTC instant. With a known fixed offset:

```text
Unix seconds = native Mac seconds - 2,082,844,800 - seconds east of UTC
```

For a known geographical city, iOpenPod uses the offset for the represented date,
not today's offset. That IANA interpretation is Host policy, not proof of Apple
firmware parity or historical settings. Zero commonly represents a missing date;
sidecar zero may explicitly clear one. This is not a universal firmware missing-
value rule: an empty native date-added slot can be initialized from the current
Firmware Calendar. `0xFFFFFFFF` is not a general date sentinel. Field-specific
sentinels must remain separate from epoch conversion. [Time contract][time], [ADR-0240][policy]

The root `mhbd` chunk has signed LE i32 `timezone_offset` at `0x6C`, in seconds
east of UTC. It supplies a captured fixed-offset fallback; it is not an event
timestamp or historical timezone database. [Root definition][mhbd]

### Playlist and Smart rule fields

The codec retains LE u32 fields `mhyp+0x18` (`timestamp`), `mhyp+0x58`
(`timestamp_2`) and `mhip+0x1C` (`timestamp`). Their exact semantics are not all
qualified. Classic 6.5's importer can use `mhip+0x1C` to populate an otherwise
empty Track date-added slot; zero can fall back to a sampled calendar value.
Do not assign every one of these fields a confident creation/modification label.
[Playlist definition][mhyp], [item definition][mhip], [qualified importer][playlist-import]

Smart date rules live in MHOD type 51 (`SLst`) inside Playlist data. Numeric
operands are relative to each **rule data payload**, after its `0x38`-byte rule
header: `+0x00` from-value (BE u64), `+0x08` from-date (BE i64), `+0x10` from-units
(BE u64), `+0x18` to-value, `+0x20` to-date and `+0x28` to-units. These are
action-dependent operands, not six independent timestamps. Absolute date bounds
and relative periods must be decoded according to the rule's field/action.
More precisely, each triple is a base, signed displacement and scale; the firmware
forms `(base + displacement * scale) mod 2^64`. Scale 86400 represents days.
The full base sentinel `0x2DAE2DAE2DAE2DAE` selects sampled day-start for the lower
bound and inclusive day-end for the upper. Zero Track dates remain numeric zero
in these comparisons. The first outer rule begins at MHOD `+0xA0`, with its
operand at `+0xD8`; nested and subsequent rules require walking their own framing.
Firmware date comparisons use calendar-day bounds; current Host relative-date
preview uses the separately documented duration policy. [Rule definition][smart],
[comparison research][comparisons]

## Play Counts: pending event dates

The header specifies row start and stride. For standard `mhdp` framing, header
`+0x04` is header length, `+0x08` is row size and `+0x0C` is row count, all LE u32.
Row `i` starts at `header_length + i*row_size`; do not assume a fixed row width.

| Row offset | Encoding | Meaning |
| --- | --- | --- |
| `0x04` | u32 in file byte order | Last played local Mac date |
| `0x18` | u32 in file byte order, when row has at least 28 bytes | Last skipped local Mac date |

The same rows contain counters and bookmarks, which are not wall-clock dates.
Rows are positional relative to the source Track table. Device events can set a
date backward after a clock correction; a smaller value is not necessarily an
invalid event. Zero, absence and the exact Finder sentinel have separate update
semantics. The application preserves incoming native date words and archives
consumed sidecar bytes while applying valid playback counts. [Codec][sidecars],
[policy][policy], [Finder contract][finder]

`PlayCounts.plist` has supported keys `tracks[].playMacOSDate` and
`tracks[].skipMacOSDate`. Parser support does not prove that every latest Classic
writes this variant. `OTGPlaylistInfo` carries Playlist membership; no datetime
field is currently qualified there.
The separate `iPod_Control/Device/PlayCounts` is a tagged store observed on
Classic 6.5; no datetime value is currently qualified in it. It must not be
confused with either playback sidecar above. [Persistence trace][persistence]

`iTunesCDB` carries the same logical chunk fields after decompression, but current
Classic capabilities do not select compressed databases. Application codec support
is not evidence that all four Classics read that file. [CDB codec][cdb],
[device capabilities][catalog]

## Images, calendars and remaining files

Classic `Device/alarms` uses outer token container `0x3a` and record container
`5`. Field `6` carries the scheduled u32 scalar; field `0x3b` carries repeat mode.
The inspected alarm arithmetic uses a 1970 calendar coordinate, whose complete
producer's UTC/local provenance remains open. These are tagged fields, not fixed
file offsets or ordinary 1904 media words. See the
[native record and scheduling report](../../../ipod-firmware-lab/notes/classic-alarm-persistence-2026-11-06.md).

Both image databases share `mhii+0x28` (`original_date`) and `mhii+0x2C`
(`exif_taken_date`), LE u32. The current Photo model treats them as local Mac
dates. Their all-four firmware date semantics are less qualified than the Track
play/skip routes. `mhii+0x24` is an observed image-order key, not a proved date.
See [image definitions][mhii] and [auxiliary file inventory][auxiliary].

Apple documents Host-provided `.ics`/`.vcs` files in `Calendars`. In iCalendar,
properties such as `DTSTART`, `DTEND`, `DUE`, `RRULE` and alarm `TRIGGER` express
events, deadlines, recurrence and alarms. `Z` denotes UTC; a `TZID` refers to
zone rules; a date-time without either is floating; `VALUE=DATE` is date-only.
These are format semantics, not a claim that every Classic implements the full
standard or every timezone component. [Apple guide][manual], [iCalendar][ical]
Native date/property and duration/trigger paths are now covered by the
[Calendar follow-up](calendar-alarm-firmware-2026-11-06.md). Full-file acceptance
and recurrence expansion remain separate from leaf parsing.

The documented `iTunesPrefs` prefix has no verified date field; its unknown
history/tail cannot be called date-free. SQLite Library/Locations/Dynamic date
columns on qualified other devices use a separate 2001 epoch, but must not be
promoted to the Classic Library format. Classic Extras.itdb is observed; its
presence alone establishes no generic SQLite datetime contract. Stopwatch logs,
voice-memo dates, remaining alarm/world-clock persistence, game saves, contact date fields,
media-container dates and filesystem timestamps require their own format audits.
Apple documents several of these date-bearing features without specifying their
private on-disk layouts. [Auxiliary inventory][auxiliary], [Apple guide][manual]

The running RTC is **not a file**. Its packed-BCD calendar and alarm banks are
PMU registers `0x59..0x5F` and `0x60..0x66`; live retained zone/DST metadata is
separate PMU storage. Reading Preferences therefore does not reveal one absolute
current timestamp. The raw RTC's UTC/local origin remains unresolved.
[Clock provider research][raw-clock]

For Library workflows, unresolved dates produce a warning, estimate or missing
value. Counts remain usable and original native evidence remains retained.
Neither saved DST nor clock correction is added to already-recorded dates again.

[preferences]: ../ipod-preferences.md
[support]: ../classic-calendar-support.md
[pref-def]: ../../src/iPodDB/preferences/definitions.py
[notifications]: classic-clock-notification-effects-2026-11-05.md
[dst-def]: ../../src/iPodDB/preferences/dst.py
[dst-research]: firmware-dst-data-and-city-identity-2026-11-06.md
[mhit]: ../../src/iPodDB/iTunesDB/shared/chunk_defs/mhit.py
[mhbd]: ../../src/iPodDB/iTunesDB/shared/chunk_defs/mhbd.py
[mhyp]: ../../src/iPodDB/iTunesDB/shared/chunk_defs/mhyp.py
[mhip]: ../../src/iPodDB/iTunesDB/shared/chunk_defs/mhip.py
[smart]: ../../src/iPodDB/iTunesDB/shared/chunk_defs/mhod_payloads/smart_rules_mhod.py
[playlist-import]: ../../../ipod-firmware-lab/notes/itunesdb/consumers-and-playlists.md
[comparisons]: clock-adjustments-and-date-comparisons-2026-11-06.md
[time]: ../ipod-time.md
[policy]: ../adr/0240-treat-calendar-dates-as-best-effort-metadata.md
[sidecars]: ../../src/iPodDB/sidecars/codec.py
[persistence]: ../../../ipod-firmware-lab/notes/itunesdb/persistence-lifecycle.md
[cdb]: ../../src/iPodDB/iTunesDB/cdb.py
[catalog]: ../../src/device_registry/data/catalog.py
[finder]: finder-playcounts-compatibility-2026-10-18.md
[mhii]: ../../src/iPodDB/ArtworkDB/shared/chunk_defs/mhii.py
[auxiliary]: auxiliary-datetime-file-inventory-2026-11-06.md
[raw-clock]: classic-raw-clock-origin-followup-2026-11-05.md
[manual]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf
[ical]: https://www.rfc-editor.org/rfc/rfc5545#section-3.3.5
