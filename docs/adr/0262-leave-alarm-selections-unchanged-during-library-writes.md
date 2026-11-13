# ADR-0262: Leave Alarm selections unchanged during Library writes

- Status: Accepted
- Date: 2026-11-13
- Supersedes: the Library-write Alarm preservation requirements in ADR-0260 and ADR-0261

By explicit user direction, Library changes leave saved Alarm selections unchanged.
Reordering or deleting Playlists can change what a native positional selector
plays, or leave a saved Playlist ID unresolved. iOpenPod accepts that native outcome.
It does not remap Alarm selectors, block Library publication because of an Alarm,
or add Alarm-file dependencies to a Library Storage Transaction.

The previously added Clock selector remapper and Mini selected-Playlist deletion
check are removed. This policy applies to all Alarm formats, including Nano 2's
Nano 1 compatibility behavior. Classic/Nano 3–5 preservation is not future work.

An explicit Alarm edit still resolves its selected sound against the captured
native Playlist catalog and checks its source before publication. These checks
ensure that the requested edit writes the chosen sound; they do not keep that
selection attached to the same Playlist through later Library changes.

Regression tests delete a selected Playlist through the normal Library save
workflow, including when the Alarm file changed or became malformed after Review.
The Library saves successfully and the Alarm bytes remain untouched.
