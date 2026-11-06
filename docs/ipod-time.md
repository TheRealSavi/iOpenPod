# iPod timestamp conversion

The [Classic datetime file map](research/classic-datetime-file-map-2026-11-06.md)
lists concrete files, byte offsets, purposes and remaining interpretation limits.

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

Device selection captures Preferences before publishing the semantic Library.
The same captured bytes feed the read-only Settings tab. Unreadable or later
changed Preferences do not block a Library save: the captured interpretation
keeps the same key/offset/provenance for that Library source. Database, sidecar and resource checks
remain enforced. The iTunes preferences file is display-only.

SQLite publication uses already-resolved Unix dates. Locations creation dates
come from Track date added; release and purchase dates also populate store date
columns. Unknown zones and ambiguous dates use the same best-effort interpretation
without blocking regeneration. Native database date words and the header offset
remain retained rather than being rewritten to endorse an estimate.

Physical Preferences editing and device clock synchronization are separate
workflows. No timezone migration is implicit in loading or saving a Library.

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
The nano 7 check explicitly asserted New York for research; its unknown city zero
still uses the diagnosed header fallback at runtime. One pre-existing nano 5
zero-Mac/nonzero-SQL skipped-date discrepancy was retained, not normalized.

The [datetime engineering guide](datetime-engineering.md) maps the current code,
Host formats, interpretation policies and unresolved firmware hints.
[ADR-0243](adr/0243-use-whenever-for-calendar-interpretation.md) records the Whenever
migration. Its regressions and conversion comparisons are separate from the
historical paired-capture check above.
