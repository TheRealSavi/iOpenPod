# ADR-0260: Bind Alarm sounds to native sources and preserve Playlist identities

- Status: Accepted
- Date: 2026-11-13
- Extends: ADR-0247 and ADR-0259
- Partly superseded by: ADR-0262 for Library-write Alarm preservation

Further [firmware research](../alarms.md#sound-persistence-and-selection) proves
persisted sound selection and the native enable transitions. The earlier
sound-preservation-only and read-only timer restrictions are superseded for these
qualified fields. Saved publication remains separate from live firmware adoption.

iPodDB exposes typed native Playlist projections for Mini, Nano 1 and Video from
the retained Library document. It retains the Master Playlist, native filters and
first-dataset order; the ordinary semantic snapshot cannot supply these indices.
Clock codecs express coupled sound-selection writes.
Mini enable lookup uses a known current source ID, never absence inferred from a
catalog that excludes generated runtime Playlists.

The Application Layer binds explicit sound choices to the captured Library
fingerprint. This decision originally also required remapping Clock indices and
blocking removal of selected Playlists during Library publication. Explicit user
direction superseded that requirement in
[ADR-0262](0262-leave-alarm-selections-unchanged-during-library-writes.md): Library
saves leave Alarm bytes unchanged and do not depend on Alarm files. The later
[Playlist investigation](../research/alarm-playlist-ordering-2026-11-13.md)
resolves native collation in all Classic/Nano 3–5 images. Source-to-native import
projection and variant array consumers still require qualification before an
equivalent Classic sound-selection projection is enabled. Automatic remapping is
not planned.

Classic and Nano 3–5 tone names come from native text contents. Qualified saved
language resolves the localized default Beep name. Bounded, unambiguous custom
collections may supply additional choices. Storage captures language/tone source
fingerprints and the application rechecks the candidate inventory. New dated
alarms require an explicit verified tone instead of the constructor's empty name.
The GUI retains native application typography, controls and unknown-state choices.

Nano 6/7 expose explicit saved duration and ending-action changes through a
separate timer-settings intent. The codec replaces only existing unique scalars,
preserves deadlines and unknown bytes, and applies native SoundIndex/SleepiPod
coupling. Nano 6's two stores publish together. Initialization loads these saved
settings; this does not authorize live start, stop, pause or cancel commands.

Standalone native vectors, source-bound virtual Storage tests and GUI lifecycle
tests verify sound editing. ADR-0262 tests Library/Alarm independence. Physical
wake, sound output and device adoption remain acceptance-test work.
