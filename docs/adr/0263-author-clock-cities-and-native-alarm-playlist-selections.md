# ADR-0263: Author Clock cities and native Alarm Playlist selections

- Status: Accepted
- Date: 2026-11-13
- Amends: ADR-0259, ADR-0260 and ADR-0261 for the newly requested controls

The user requested the remaining Playlist selection and city-management flows.
Classic and Nano 3/4 Alarm selectors address a native imported array whose
filtering, title composition and collation differ from the Library sidebar.
Nano 5 instead loads that array from `Library.itdb` joined to `Dynamic.itdb`,
ordered by saved `name_order`. iPodDB owns both pure projections; the Application
Layer captures their sources through Storage. Explicit sound edits bind the
chosen selector to those source fingerprints, including both SQLite companions.
Using the semantic Library snapshot would silently select a different Playlist.

The existing Sound dropdown offers one tone or Playlist. Explicit selection
clears the opposite field; unrelated edits preserve native combined tone/Playlist
states. Existing enabled gates remain unchanged unless the user changes Enabled.
Creation uses the qualified native defaults. An unsupported native string import
or ambiguous SQLite sort positions cannot qualify a new selector; existing saved
selectors remain untouched. Runtime-generated collections beyond the captured
imported prefix are not invented.

For Nano 1 and Video, a Clock City owns its daily Clock Alarm. iPodDB exposes the
204 native region/ordinal identities and emits the native 125-byte city record.
The UI searches those identities, edits manual DST, and removes the whole city
record. Duplicate cities and deletion of the final city are allowed. Absent or
empty stores accept explicit creation; merely reading one does not synthesize
the firmware's fallback California city. Host timezone rules are not substituted
for these native identities or flags.

The user's Nano 2 compatibility direction includes these city operations, while
its encrypted implementation remains unverified. This supersedes ADR-0261's
earlier exclusion of city creation/removal. It enables no Preferences writer.
ADR-0262 remains unchanged: Library changes never preserve, remap or block on
Alarm selections. Firmware bugs and adoption timing remain outside this work.

See [Alarms](../alarms.md), the
[city authoring evidence](../research/alarm-legacy-city-authoring-2026-11-13.md)
and the [native Playlist investigation](../research/alarm-playlist-ordering-2026-11-13.md).
