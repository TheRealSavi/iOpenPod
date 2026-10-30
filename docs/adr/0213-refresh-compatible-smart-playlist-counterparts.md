# ADR-0213: Refresh compatible Smart Playlist counterparts

- Status: Accepted
- Date: 2026-10-30
- Amends: ADR-0024's comparison of affected Playlist counterpart membership
- Retains: ADR-0100's selection-time playback commit and ADR-0142's automatic refresh

## Context

[Issue 294](https://github.com/TheRealSavi/iOpenPod/issues/294) reports repeated
dataset-2 Playlist relationship errors while selecting an iPod Video 5.5. A
synthetic Library reproduces the exact error when a live Smart Playlist's copies
have identical definitions but different saved membership. Automatic refresh
evaluates the desired membership, then reconciliation rejects the copies because
their old ordered Track lists differ. Its occurrence mapping also assumes every
canonical occurrence exists in the other copy.

The Application Layer currently submits only the projected canonical Playlist.
When that copy is already current, a stale counterpart is invisible to ordinary
semantic change detection. Skipping refresh would violate ADR-0142 and leave the
relationship problem unresolved.

Original iOpenPod's dataset research and `_playlist_builder` retain independent
dataset lists and evaluate live Smart Playlists against the completed Track list.
This supports regenerating saved results from matching definitions, rather than
requiring those results to agree before evaluation. The reporter has supplied no
database or sidecars, so the particular differences on that iPod remain unknown.

## Decision

Keep automatic Smart Playlist evaluation on selection, ordinary saves, and Sync.
The Application Layer supplies the evaluated snapshot and identifies retained,
supported live Smart Playlists whose native copies must receive those entries.
iPodDB validates that explicit refresh intent and detects stale native membership
or positions, including when the canonical snapshot does not change. Only actual
native differences produce an additional repair change in the review.

For these refreshes, matching Playlist identity, projected metadata, and Smart
definition establish correspondence. Old saved membership need not agree. The
writer applies the evaluated ordered membership to each copy, maps surviving
occurrences to that copy's own records, and allocates new occurrences when no
matching retained occurrence exists. Missing canonical occurrences never reuse
another Track's numeric occurrence identity.

Definition, name, parent, sort, kind, and system-marker conflicts still block the
write; diagnostics identify the Playlist and differing source fields. Ordinary
Playlist membership conflicts retain ADR-0024's existing protection. Dataset 5,
unsupported definitions, and Smart Playlists without Live updating are not
automatically refreshed through this intent. No rule evaluator moves into iPodDB.

Unchanged drafts without explicit refresh remain byte-exact. Matching copies
already containing the evaluated membership and positions do not force a write.
Independent native verification checks every refreshed counterpart, even when
the canonical semantic snapshot was already current. Storage publication,
sidecar archives, verification, and recovery remain unchanged.

## Consequences and validation

Stale saved results no longer block refresh or safe On-The-Go additions for
otherwise matching live Smart Playlists. Genuine definition conflicts still need
investigation; this does not select a conflicting rule set as repair authority.

Regressions cover selection with playback deltas and empty On-The-Go semaphores,
canonical-current and stale copies, missing members, safe On-The-Go additions,
per-copy occurrence metadata, byte-exact no-ops, invalid refresh intent, conflict
preservation, and rejection of injected stale output. These are synthetic and
virtual-device checks, not confirmation of the reporter's database or physical
firmware behavior.
