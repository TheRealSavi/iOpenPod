# iPod timestamp reconciliation evidence

Investigated 2026-09-30. This note separates external implementations, direct
observations of the supplied device captures, and implementation recommendations.
It supplements [the Preferences research](ipod-preferences.md). The captures were
read without modification; their private contents are not committed as fixtures.

## Finding

The supplied iTunesCDB/SQLite pairs support **historical local time for ordinary
Track dates, UTC Mac time for release/purchase dates, and UTC Core Data time in
SQLite**. One current timezone offset cannot reproduce their dates across daylight
saving changes. The MHBD offset is insufficient to identify a historical timezone.

This differs from libgpod's fixed-offset approximation and its SQLite conversion.
Preserve that disagreement explicitly instead of presenting either implementation
as a complete specification.

## What primary implementations establish

[libgpod's timestamp helper](https://github.com/gtkpod/libgpod/blob/main/src/itdb_tzinfo.c#L46)
uses `device->timezone_shift` for Mac/Unix conversion and preserves zero as unset.
Its [city resolver](https://github.com/gtkpod/libgpod/blob/main/src/itdb_tzinfo.c#L160)
looks up the offset at the current time, then reuses that shift for all dates.
The Preferences reader falls back to the Host timezone; that fallback is not
suitable evidence about an unknown iPod timezone.

[Track parsing](https://github.com/gtkpod/libgpod/blob/main/src/itdb_itunesdb.c#L2502),
[Smart Playlist dates](https://github.com/gtkpod/libgpod/blob/main/src/itdb_itunesdb.c#L1822),
[playlist timestamps](https://github.com/gtkpod/libgpod/blob/main/src/itdb_itunesdb.c#L2259),
and [Play Counts](https://github.com/gtkpod/libgpod/blob/main/src/itdb_itunesdb.c#L987)
use the device helper. The separate MHBD field at `0x6C` is
[read into `itdb->tzoffset`](https://github.com/gtkpod/libgpod/blob/main/src/itdb_itunesdb.c#L3165)
and [written back](https://github.com/gtkpod/libgpod/blob/main/src/itdb_itunesdb.c#L3889).
This does not establish it as the encoding offset for every retained Mac date.

[libgpod's SQLite helper](https://github.com/gtkpod/libgpod/blob/main/src/itdb_sqlite.c#L47)
calculates `tv - 978307200 - tzoffset`, with
[`tzoffset` copied from the MHBD value](https://github.com/gtkpod/libgpod/blob/main/src/itdb_sqlite.c#L2279).
It is not copied from `device->timezone_shift`. Its comment's reference to 01:00
does not change the numeric epoch: `978307200` is 2001-01-01 00:00 UTC.

There is independent support for another SQLite treatment:
[foo_dop converts local Mac values to UTC before changing epochs](https://github.com/reupen/ipod_manager/blob/main/foo_dop/writer_sqlite.cpp#L92),
without subtracting the MHBD field. Its
[time helpers distinguish local and UTC values](https://github.com/reupen/ipod_manager/blob/main/foo_dop/itunesdb_helpers.cpp#L124).
It maps [location creation to the Track's date added](https://github.com/reupen/ipod_manager/blob/main/foo_dop/writer_sqlite.cpp#L1147)
and [explicitly treats podcast release dates as UTC](https://github.com/reupen/ipod_manager/blob/main/foo_dop/writer_sqlite.cpp#L1215).
Its [store purchase/release conversions are marked FIXME](https://github.com/reupen/ipod_manager/blob/main/foo_dop/writer_sqlite.cpp#L1232),
so those calls do not settle that question.

## Read-only capture comparison

Inputs were the supplied `ipods/nano5` and `ipods/orig_nano7` trees beneath
`C:/Users/JohnG/Coding`, plus a header-only read from the connected `D:` iTunesDB.
For each captured tree, the compared artifacts were:

- `iPod_Control/Device/Preferences`;
- `iPod_Control/iTunes/iTunesCDB`;
- `iPod_Control/iTunes/iTunes Library.itlp/Library.itdb`;
- `iPod_Control/iTunes/iTunes Library.itlp/Dynamic.itdb`; and
- `iPod_Control/iTunes/iTunes Library.itlp/Locations.itdb`.

Physical CDB reads were capped at 8 MiB and decompressed output at 16 MiB. SQLite
connections used `mode=ro&immutable=1`; queries selected only persistent IDs and
date fields, capped at 4,096 rows. IDs were used internally for joins and were not
reported. Both captures contained fewer Tracks than the query limit.

| Capture | Track count | MHBD signed seconds | Preferences city |
| --- | --- | --- | --- |
| nano 5 | 51 | -18,000 | `0x1D`, New York catalog entry |
| original nano 7 | 832 | -14,400 | `0x00`, unknown |
| connected `D:` | Not examined | -14,400 | `0x21`, Detroit catalog entry |

For the numerical comparison, define:

```text
M = native Mac timestamp
S = paired SQLite timestamp
U = S + 978307200
delta = M - 2082844800 - U
```

Every nonzero paired value in the following table matches exactly. The local
column means `delta` equals the historical `America/New_York` UTC offset at `U`;
the UTC column means `delta = 0`.

| Native MHIT field | SQLite counterpart | Observed encoding | nano 5 pairs | nano 7 pairs |
| --- | --- | --- | --- | --- |
| `0x20`, last modified | `Library.item.date_modified` | Historical local | 51 | 832 |
| `0x68`, date added | `Locations.location.date_created` | Historical local | 51 | 832 |
| `0x58`, last played | `Dynamic.item_stats.date_played` | Historical local | 44 | 408 |
| `0xA0`, last skipped | `Dynamic.item_stats.date_skipped` | Historical local | 9 | 423 |
| `0x8C`, release date | `Library.item.date_released` and `store_info.date_released` | UTC | 1 | 547 |
| `0xDC`, named `date_added_to_itunes` in iPodDB | `Library.store_info.date_purchased` | UTC | 1 | 530 |

The last field's current code name is misleading for these captures: its exact
match is the store purchase date, not the device's date added. No assumption about
renaming the field is necessary to preserve its native bytes and convert its epoch
correctly.

Seasonal variation appears within each single database. For modified dates, nano 5
has 50 deltas of -18,000 and one of -14,400; nano 7 has 472 and 360 respectively.
For played dates, the counts are 17/27 and 212/196. For skipped dates, they are 7/2
and 130/293. Historical New York rules explain every one of these pairs; a fixed
MHBD offset or the offset at today's date does not.

Playlist creation dates also match their SQLite counterparts: two nano 5 pairs
have delta -18,000, and eleven nano 7 pairs have delta -14,400. These particular
values do not distinguish current-offset from historical conversion.

One nano 5 skip pair has a zero Mac value and a nonzero SQLite value. It was
excluded from the nonzero-pair comparison; it is evidence that the artifacts need
not contain identical playback state, not a reason to replace the zero sentinel.

New York is an observed catalog choice on nano 5 and a successful research
hypothesis for nano 7. The latter's city zero does **not** authorize selecting New
York at runtime. Other zones can share the same seasonal offsets. These comparisons
also do not establish who last wrote each artifact or independently recover the
real-world time of an event. They establish exact, field-specific relationships
between the supplied bytes.

## Recommended deterministic contract

Freeze the **timezone interpretation and provenance** for one loaded Library,
rather than freezing today's offset for every historical timestamp. A recognized
city provides historical timezone rules. An older offset-coded Preferences layout
provides only a fixed offset. If Preferences cannot supply a usable timezone, a
valid MHBD offset may be an explicit, diagnosed fixed-offset fallback; it cannot
recover missing historical DST or identify a city. Never infer the iPod timezone
from the Host timezone. If neither source is usable, preserve native values while
withholding an invented absolute local-date interpretation.

For the evidenced local Track fields, convert the native number to a local calendar
date relative to 1904 and resolve that date in the captured device timezone. The
inverse converts an absolute Unix instant to local calendar fields before measuring
seconds from 1904. For release and store purchase dates, use the epoch difference
alone. For SQLite, retain UTC Core Data conversion:

```text
Local Mac write: M = U + 2082844800 + offset_at(U)
UTC Mac write:   M = U + 2082844800
SQLite write:    S = U - 978307200
```

Zero remains unset, rather than a request to convert an epoch. Retained nonzero
values must fit their actual native field. Range checks should allow representable
pre-1970 instants instead of turning every nonpositive Unix value into unset.

Do not subtract the MHBD offset again when serializing an already absolute Unix
instant into SQLite. The proposed libgpod-style extra subtraction conflicts with
these captures and is unnecessary in the foo_dop path. Retain the header value;
do not normalize it or rewrite every date just because Preferences disagrees.
Preserve native bytes for unchanged fields, including dates that cannot be resolved
unambiguously. Use the correct semantic source for SQLite location creation:
date added, not last modified.

A local time in a repeated DST hour can name two instants; a skipped hour can name
none. Detect these cases instead of silently choosing a fold or normalizing a gap.
An existing raw timestamp can be preserved, but a newly requested exact instant
must not be claimed to survive the format when its local encoding loses the
distinction. A later device timezone change also cannot reveal the zone used for
older records. This increment should not invent migration history.

## Nano 3 DST and other evidence gaps

The [historical Preferences table](https://github.com/raleighlittles/iTunesDB-Parser/blob/main/itunesdb_docs/README.md#L18945)
identifies nano 3 byte `0x6BC` as 0 or 60 for DST off/on. It does not establish the
formula combining that setting with a city ID. libgpod ignores this byte and uses
the city's current timezone offset. Adding 60 minutes to an offset that already
includes DST risks applying it twice. Replacing the city's DST component with the
byte is plausible, but was not verified against firmware or controlled captures.
Keep the flag separate and report the unresolved manual-DST interpretation rather
than asserting either formula as proven.

[libgpod's Photo parser](https://github.com/gtkpod/libgpod/blob/main/src/db-artwork-parser.c#L257)
and [writer](https://github.com/gtkpod/libgpod/blob/main/src/db-artwork-writer.c#L493)
convert both MHII original and digitized dates through device Mac time. This is
evidence against exposing native Photo dates as Unix seconds directly. No paired
Photo capture established historical DST handling independently. Absolute Smart
Playlist dates and playlist timestamps likewise have local-time implementation
evidence, while relative durations must remain durations.

No capture here tests another geographical region, a device timezone change,
manual DST toggling, DST transition ambiguity, or writes followed by device
playback. The historical-local/UTC distinction is strong for the compared Track
fields and remains an explicit interpretation for other generations. These limits
should remain visible in diagnostics and tests rather than being hidden behind
Host-local fallback or automatic timezone migration.
