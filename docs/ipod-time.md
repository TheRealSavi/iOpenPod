# iPod timestamp conversion

`iPodDB.device_time` is the shared conversion contract. `IPodLibrary.device_time`
retains a `DeviceTimeContext`: supplied timezone rules, their provenance, the
independent database header offset, and any interpretation limitation. The
Application Layer resolves Preferences cities with `zoneinfo` and declares the
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
contains timezone rules rather than a single offset evaluated at load time.

The inverse checks native u32 limits and unique local-time representation. Both
instants in a repeated DST hour would produce the same native field, so neither
is accepted as a new exact local timestamp. Retained gap/fold values are displayed
as unavailable and reported, but unrelated edits preserve their native bytes.
Incoming playback dates use stricter consumption rules: an ambiguous date rejects
the complete playback input, including valid earlier rows. Binary date words
representing semantic Unix zero, or an explicit zero clear over an unavailable
nonzero native date, also remain pending because the current semantic-only write
contract cannot faithfully represent the requested change.
Unknown zones do not silently become UTC. Valid header-only fallback is explicit
and cannot recover historical DST. These policies cannot reconstruct a device's
past timezone selections or compensate for an incorrectly set physical clock.

City mappings use geographical identity, not offset equality alone. The
[follow-up audit](research/classic201-additional-contracts-2026-10-26.md#city-identity-corrections)
corrects San Jose, San Juan, Rio de Janeiro and Victoria. Qualified Classic city
`0x26` withholds a contradictory London mapping and carries its reason into the
existing header-fallback diagnostic. Interpretation preserves original Preferences
and date bytes; it does not migrate historical timestamps.

Device selection captures Preferences before publishing the semantic Library.
The same captured bytes feed the read-only Settings tab. Preparation and Storage
publication check the captured file fingerprint or absence. Unknown layouts can
still be fingerprinted; a failed bounded read cannot authorize a save. The iTunes
preferences file is display-only and is not a clock dependency.

SQLite publication uses already-resolved Unix dates. Locations creation dates
come from Track date added; release and purchase dates also populate store date
columns. An unresolved retained Track date blocks SQLite regeneration so a full
replacement cannot discard that evidence. The database header offset is retained
unchanged, not rewritten to match Preferences.

Physical Preferences editing and device clock synchronization are separate
workflows. No timezone migration is implicit in loading or saving a Library.

Classic 2.0.1 maintains an adjusted calendar using a separate software bias;
manual corrections can enter that bias. New play/skip dates already encode the
adjusted calendar, so saved bias and DST bytes must not be added again. The
qualified Classic Preferences view exposes those observations read-only. The raw
hardware clock's UTC/local basis and all downstream effects of timezone-change
callbacks remain unresolved.

Binary Play Counts replaces present dates even when they move backward or clear
to zero, subject to the Finder sentinel and representability limits above. A date
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

Read-only verification of the implementation matched 3,729 nonzero paired date
values across the supplied nano 5 and nano 7 CDB/SQLite captures. Both CDB
round trips were byte-identical and all eight input file hashes stayed unchanged.
The nano 7 check explicitly asserted New York for research; its unknown city zero
still uses the diagnosed header fallback at runtime. One pre-existing nano 5
zero-Mac/nonzero-SQL skipped-date discrepancy was retained, not normalized.
