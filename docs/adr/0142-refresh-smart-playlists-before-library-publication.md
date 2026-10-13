# ADR-0142: Refresh Smart Playlists before Library publication

- Status: Accepted
- Date: 2026-10-13
- Extends: ADR-0022, ADR-0035, ADR-0073, and ADR-0076
- Supersedes: ADR-0022's prohibition on automatic reevaluation during saves

The user requested evaluation of Smart Playlists with Live updating enabled at the
end of every Sync, including quick metadata changes. The shared Application Layer
Library preparation path now refreshes their supported membership after the
workflow finishes building its desired Tracks and Playlists, before database preparation and
publication. Full Sync, automatic Library saves, and manual Library saves therefore
publish the refreshed membership in the same verified Storage Transaction. Review
contains that membership; accepting a review does not reevaluate it again.

The Original iOpenPod's `_playlist_builder._reevaluate_live_spls` is the behavioral
baseline for matching against the final Track list. Smart Playlists with Live
updating disabled retain their saved membership during automatic refresh. Explicit
rule edits and Evaluate now retain their existing behavior. A Sync with no other
changes still evaluates supported Smart Playlists with Live updating enabled,
allowing date rules and stale memberships to refresh. If memberships are already
current, the unchanged review succeeds without
requiring a database replacement. A failed Sync with no successfully prepared work
retains the existing failure behavior.

Each pass uses one captured time and the existing matching, limit, and Playlist
Sort Order rules. Surviving occurrences keep their entry identities and private
metadata. ADR-0035's reference semantics remain: Playlist references, including
Playlist Folder descendants, read saved membership from the completed input draft.
All refreshed Smart Playlists read that same snapshot, so results do not depend on
their enumeration order and cyclic references do not cause recursive evaluation.

Unsupported imported definitions and firmware-managed Playlists retain their saved
membership and rules. An invalid supported definition with Live updating enabled
or a missing reference blocks preparation with the Playlist name and reason; it
cannot silently erase membership.
Preparation remains cancellable, does not mutate the live Library Workspace, and
does not write device files. Only verified publication adopts the refreshed Library.
