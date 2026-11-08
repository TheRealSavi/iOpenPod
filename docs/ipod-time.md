# iPod timestamp conversion

The [Classic datetime file map](research/classic-datetime-file-map-2026-11-06.md)
lists concrete files, byte offsets, purposes and remaining interpretation limits.
The [Mini 2 and Video comparison](research/mini-video-datetime-firmware-2026-11-06.md)
records their distinct clock paths and the Video alarm-field correction; the
Classic file map is not a universal layout for earlier devices.

`iPodDB.device_time` is the shared conversion contract. `IPodLibrary.device_time`
retains a `DeviceTimeContext`: a captured IANA key or whole-second Whenever
`TimeDelta` effective offset, its provenance, the
independent database header offset, and any interpretation limitation. The
Application Layer resolves Preferences cities to IANA keys; Whenever interprets
those keys. The application declares the
`tzdata` dependency for systems without an IANA database, especially Windows.
This is Host interpretation policy. A selected city is not proof of the raw
hardware clock's timezone, historical city selections, or firmware/IANA parity.

| Native field | Read into Library | Write from Library |
| --- | --- | --- |
| Track modified, added, played, skipped | Local Mac date to UTC Unix instant | UTC Unix instant to local Mac date |
| Track released, added-to-iTunes/purchased | Subtract 2,082,844,800 | Add 2,082,844,800 where writable |
| Photo original/taken | Local Mac date to UTC Unix instant | UTC Unix instant to local Mac date |
| Absolute Smart Playlist date | Local Mac date to UTC Unix instant | UTC Unix instant to local Mac date |
| Supported relative Smart Playlist period | Host duration interpretation | Host duration encoding |
| SQLite dates | Generated from semantic Library | Subtract 978,307,200; no local shift |

For fixed offsets, local conversion is:

```text
Unix = Mac - 2,082,844,800 - seconds_east_of_UTC
Mac = Unix + 2,082,844,800 + seconds_east_of_UTC
```

For a city, the offset depends on the represented date. For example, New York
midnight is 05:00 UTC on January 1, 2024 and 04:00 UTC on July 1, 2024. Loading the
Library in summer must not shift its winter events by an hour. The frozen context
retains the IANA key rather than a single offset evaluated at load time. It does
not snapshot a tzdb version: Whenever resolves the available historical rules.

Dates never block Library loading, editing, saving or Sync. A repeated DST hour
uses the occurrence matching the captured header offset when possible, otherwise
the earlier UTC occurrence. A skipped hour uses the pre-transition offset. An
unknown zone uses a valid captured fixed offset, or an explicit UTC estimate.
Approximation produces a warning; no Host timezone or current clock is consulted.
These rules cannot reconstruct past city selections or an incorrectly set clock.

Unchanged native words remain intact. Binary Play Counts carries exact incoming
date words through writing and verification, separately from the semantic instant.
This preserves gap labels and nonzero words that project to Unix zero, and allows
explicit zero clears. Subsequent semantic edits override the captured date.
Newly authored dates are bounded to the native range before validation; missing
dates remain zero. Unsupported layout fields retain their previous values.
Smart absolute bounds are ordered by their native calendar representation, and
relative periods are bounded to the supported positive range. Verification uses
the resolved values. See [ADR-0240](adr/0240-treat-calendar-dates-as-best-effort-metadata.md).

City mappings use geographical identity, not offset equality alone. The
[follow-up audit](research/classic201-additional-contracts-2026-10-26.md#city-identity-corrections)
corrects San Jose, San Juan, Rio de Janeiro and Victoria. Qualified Classic city
`0x26` withholds a contradictory London mapping and carries its reason into the
existing header-fallback diagnostic. Interpretation preserves original Preferences
and date bytes; it does not migrate historical timestamps.

## Captured clock sources

Device selection captures qualified clock settings through a bounded, verified
Storage read before projecting the semantic Library. The interpretation requires
the connected device's qualified firmware identity and the source's expected
framing; similar file sizes or neighboring settings do not establish a clock
layout. XML version and an embedded software-version value cannot qualify the
connected firmware. The Nano 7/refresh pair, like the later Classic 160GB pair,
requires explicit updater-family identity. The following latest targets have
distinct contracts:

| Device and firmware | Clock evidence used for Library dates | Limits |
| --- | --- | --- |
| Mini 1 and Mini 2 / 1.4.1 | Binary Preferences selector supplies an effective fixed offset. | Already includes the selector's DST choice; it supplies no geographical identity or historical transitions. |
| Nano 1 / 1.3.1, Nano 3 / 1.1.3, Nano 4 / 1.0.4 | No qualified saved clock source. | Use a valid database header offset, otherwise UTC. Nano 4's extensionless named store does not establish a timezone. |
| Video 5/5.5 / 1.3 | No qualified saved timezone source. | The former timezone field is an alarm projection. Use the header/UTC fallback. |
| Classic 6 / 1.1.2, 6.5 / 2.0.1, 7 / 2.0.4, 7.5 / 2.0.5 | Qualified full-width saved city selects audited IANA rules. | City zero and contradictory or unknown mappings fall back. Saved bias, DST and annual rules are separate observations. |
| Nano 5 / 1.0.2, updater 34 | `DateTime.TimeZone` in `iPodSettings.xml` selects an explicitly audited geographical IANA mapping. | The firmware's signed-minute base-offset table is not an effective-offset fallback. |
| Nano 6 / 1.2, updater 36; Nano 7 / 1.0.4, updater 37; Nano 7 refresh / 1.1.2, updater 39 | The same XML key selects the exact target's packaged timezone record name, subject to the Host mapping audit. | Packaged rule semantics and live override selection are not reproduced; contradictory mappings fall back. |

For the qualified Nano XML targets, iPodDB returns typed clock evidence containing
the raw setting and its interpreted city; the Application Layer validates the
audited IANA key with Whenever and captures it as `PREFERENCES_CITY`. The source is
`iPod_Control/Device/iPodSettings.xml`, not the optional neighboring binary
Preferences blob. World Clock entries, 12/24-hour display settings and the Nano 6
timer store do not replace this source. Nano 5 withholds Manchester (city 38) and
city 205, which is in the native table but beyond the registered maximum of 204.
Nano 6/7 withhold three contradictory label/record pairs: Manchester (38) with
`America/New_York`, Cape Town (118) with `Africa/Bissau`, and Chennai (185) with
`Asia/Colombo`. These remain observable without silently choosing either
interpretation.

Missing, unreadable, malformed, duplicate or unsupported clock settings and
unavailable Host timezone rules retain a diagnostic and use a valid database
header offset or an explicit UTC estimate.
Missing or conflicting identity cannot grant a legacy clock decoder to a
recognized latest Nano 3 or Classic frame. In particular, failed qualification
must not reinterpret Nano 3 bytes as a city or narrow a Classic u32 city to u16.
These cases retain their source and use the nonblocking header/UTC fallback.

A qualified binary Preferences file with a reset request also withholds its saved
clock settings because the firmware discards that payload. Readable settings and
raw values remain available for inspection. A Nano base offset alone never
becomes an effective offset, and neither saved DST nor clock bias is added to
native dates. The selected city does not prove that firmware has adopted the
saved file or that past dates used the same city.

The Device Time Context is frozen for that Library source. Reads and explicit new
date writes use the same captured interpretation in opposite directions; unchanged
native date words remain preserved. Unreadable or later changed Preferences,
including the Nano XML file, do not become Library save preconditions. Their
capture fingerprint verifies the initial read, not a later Library publication.
Database, sidecar, resource and device-session checks remain enforced. Explicit
Preferences editing is separately source-checked and does not reinterpret an
already loaded Library. The iTunes preferences file is display-only.

SQLite publication uses already-resolved Unix dates. Locations creation dates
come from Track date added; release and purchase dates also populate store date
columns. Unknown zones and ambiguous dates use the same best-effort interpretation
without blocking regeneration. Native database date words and the header offset
remain retained rather than being rewritten to endorse an estimate.

Physical Preferences editing and device clock synchronization are separate
workflows. No timezone migration is implicit in loading or saving a Library.

## Classic firmware evidence and remaining limits

All four latest Classic targets maintain an adjusted calendar using a separate
software bias; manual corrections can enter that bias. New play/skip dates already encode the
adjusted calendar, so saved bias and DST bytes must not be added again. The
qualified Classic Preferences view exposes those observations read-only. The raw
hardware clock's UTC/local basis remains unresolved.
The latest [early](research/classic-early-boot-rtc-2026-11-05.md) and
[later](research/classic-later-boot-rtc-2026-11-05.md) boot traces qualify all four
loaders. Their identified PMU writes do not establish a civil-calendar seed;
an unexplained write to register `0x58` prevents claiming that initialization
leaves the running RTC unchanged. This uncertainty adds no Library prerequisite.

The inspected SCSI `WRITE BUFFER` calendar command in all four targets imports
explicit civil fields, a signed quarter-hour effective offset and a DST byte.
It reaches the software-correction setter, not a proven initialization of the
Raw Hardware Clock. Valid Host calendar imports can change runtime correction
without telling us the raw RTC's UTC/local basis. The
[command and boot-provider follow-up](research/classic-raw-clock-origin-followup-2026-11-05.md)
records payload handling and direct live-metadata updates. The notification
trace below extends that investigation. The matching `READ BUFFER` response is also an adjusted
calendar, not a raw RTC measurement. There is no application device-clock writer.

The [notification follow-up](research/classic-clock-notification-effects-2026-11-05.md)
now traces the Host clock event through queued application handling on all four
targets. The handler copies live correction into Preferences, reconciles the
saved city, normalizes Saved DST State to zero or one, and marks Preferences dirty.
Delivery and later disk persistence are separate boundaries; a captured file does
not prove that every pending notification has run. Classic 6 city reconciliation
compares base offset; the later targets additionally compare their current-date
DST predicate. A saved city can therefore be an automatic match, not independent
evidence of the user's location or historical settings. iOpenPod explains that
uncertainty, retains native dates and uses its existing non-blocking fallbacks.
If no matching city exists, the inspected firmware can select city ID zero.
That value has no geographical mapping; iOpenPod reports the evidence and falls
back without adopting the firmware's invalid-city offset arithmetic.

The deferred clock-change collection is now traced to concrete MediaItem objects
in all four images. Its selected virtual method refreshes a protected-media timing
cache; it does not directly rewrite ordinary added/played/skipped dates or refresh
Smart day contexts. The inspected membership loops initialize a fresh context and
reuse their sampled day bounds within that evaluation. This narrows the earlier
callback uncertainty without claiming
that every notification recipient or indirect callee is understood. iOpenPod does
not rebase retained Track dates when city, DST or bias observations change. The
[observer follow-up](research/classic-clock-change-observers-2026-11-05.md) records
the independently checked constructors, registration and vtable targets.

Firmware Calendar, Saved DST State and Firmware DST Rules are separate domain
observations. On Classic 6.5, 7 and 7.5, the inspected automatic DST refresh also
has a live predicate cache distinct from the saved state. Its edge-triggered routine samples the predicate three
times around clock resampling; the manual action does not establish a durable
automatic-DST disable flag. Classic 6's inspected clock poll lacks that automatic
route. The raw-provider direct-call audit found an alarm
write route, not proof of how the running hardware clock was initialized.
See the [clock research](research/clock-adjustments-and-date-comparisons-2026-11-06.md).

The optional `Device/dst` file now has a lossless read-only model with explicit
Classic 2.0.1/2.0.4/2.0.5 profiles. Later firmware adds two prefix bytes, changes
the last-week selector, and corrects earlier weekday/February arithmetic defects.
The application now qualifies all three annual-file consumers using their latest
Classic Calendar Target identity. Classic 6 / 1.1.2 has qualified saved-clock
fields but retains this optional file opaquely. Short or unreadable files cannot block
Library work. Saved rules do not change historical date conversion or add write
preconditions. See [the codec contract](ipod-preferences.md#saved-firmware-dst-rules)
and [ADR-0241](adr/0241-inspect-firmware-dst-rules-as-optional-evidence.md).

All four latest targets share the full u32 saved city, raw DST byte and clock-bias
field locations, with independently qualified Preferences extents and versions.
Current hardware evidence takes precedence over weaker cached release/family
values; conflicting strongest values remain unqualified. The two later 160GB
targets require explicit updater identity. Qualified but unexpected Preferences
framing remains opaque to avoid aliasing a full city ID to its low halfword.
See [ADR-0242](adr/0242-qualify-the-latest-classic-calendar-targets.md) and
[the per-target support and questions](classic-calendar-support.md).

Host Smart relative-date previews retain the documented rolling-duration policy.
Inspected comparisons in all four latest Classic images instead use inclusive
calendar boundaries; future dates after a clock setback can therefore produce
different membership.
The research records four distinguishing cases and independently checks the later
and earlier consumers without silently changing current Host behavior.

Binary Play Counts replaces present dates even when they move backward or clear
to zero, subject to the Finder sentinel and layout limits above. A date
is independent of its counter delta. See [the sidecar contract](playback-sidecars.md).
Smart relative rules with nonzero upper displacements remain unsupported instead
of losing an endpoint. Supported Host preview still uses a rolling duration;
the inspected firmware's inclusive calendar-day window is a different policy.

See [ADR-0098](adr/0098-capture-device-time-context-for-library-dates.md) and the
[capture/source comparison](research/ipod-time-reconciliation.md) for evidence,
generation-specific uncertainty, and the decision not to copy libgpod's formulas
unchanged.
The [firmware follow-up](research/classic201-clock-semantics-2026-10-26.md) and
[ADR-0196](adr/0196-adopt-firmware-clock-and-date-evidence.md) record these later
corrections without replacing the paired-capture evidence below.

Before the Whenever migration, read-only verification matched 3,729 nonzero paired date
values across the supplied nano 5 and nano 7 CDB/SQLite captures. Both CDB
round trips were byte-identical and all eight input file hashes stayed unchanged.
The nano 7 check explicitly asserted New York for research; it did not qualify a
saved primary city. A current capture without a qualified city still uses the
diagnosed header fallback. One pre-existing nano 5
zero-Mac/nonzero-SQL skipped-date discrepancy was retained, not normalized.

The [datetime engineering guide](datetime-engineering.md) maps the current code,
Host formats, interpretation policies and unresolved firmware hints.
[ADR-0243](adr/0243-use-whenever-for-calendar-interpretation.md) records the Whenever
migration. Its regressions and conversion comparisons are separate from the
historical paired-capture check above.
