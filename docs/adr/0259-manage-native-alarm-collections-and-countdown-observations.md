# ADR-0259: Manage native Alarm collections and countdown observations

- Status: Accepted
- Nano timer support superseded by: [ADR-0267](0267-remove-nano-countdown-timer-support.md)
- Date: 2026-11-13
- Extends: ADR-0247 and ADR-0248
- Sound and timer restrictions extended by: [ADR-0260](0260-bind-alarm-sounds-to-native-sources-and-preserve-playlist-identities.md)

The [lab-wide investigation](../alarms.md) qualifies three distinct Clock Alarm
stores and a separate Countdown Timer. Reusing Video's Preferences projection
would edit derived state; treating a saved timer deadline as a command would
claim a protocol the evidence does not establish.

iPodDB therefore owns separate lossless Mini, per-city Clock and dated Alarm
codecs, plus a read-only countdown inspector that reuses bounded named-settings
parsing. Classic and Nano 3–5 can create records from independently verified
constructor defaults and remove exact spans. They expose native date/time,
repeat, predefined label and canonical enable edits. Nano 1/Video edit existing
per-city time and canonical enable fields. Mini enable editing requires a zero
saved Playlist ID; nonzero IDs depend on native Library ordering and stay retained.
Sound selection, city changes and live scheduling remain outside these writers.

Device Registry retains exact firmware qualification for every alarm write.
Application intents include creation and removal in the same identity recheck,
source-precondition and Storage Transaction workflow as existing edits. Missing
collections can be created only when their absence was observed; unreadable or
ambiguous sources never authorize replacement. GUI widgets receive typed saved
observations and submit intents, without device paths or direct I/O.

Nano 6/7 expose saved countdown presets and deadlines without a writer, Host
countdown or running-state claim. Native availability permits navigation even
when saved-file qualification is unavailable. Nano 2 follows its documented
native Clock availability, while encrypted firmware keeps file editing closed.
Optional failures remain local to Extras and never become Library dependencies.

Saved publication and live firmware adoption remain separate. Standalone native
vectors, virtual Storage transactions and GUI lifecycle tests validate the host
contract; physical wake, sound and reload acceptance are still distinct evidence.
