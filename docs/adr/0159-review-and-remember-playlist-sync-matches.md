# ADR-0159: Review and remember Playlist Sync matches

- Status: Accepted
- Date: 2026-10-19
- Amends: ADR-0076

## Decision

Review presents each supported Host Playlist with its iPod target, proposed name,
membership and order changes, and any reason it cannot sync. Users may skip an
individual Playlist, choose an existing regular top-level iPod Playlist, or create
a new one. These choices apply to the current Review and do not change Track
selection. Explicit Track removals still remove their occurrences from all
Playlists. Nested, Smart and firmware-managed Playlists remain outside Host
Playlist reconciliation.

Match by a previously successful association first, otherwise by a unique
case-insensitive name. Ambiguous names, unavailable saved targets and competing
selected Host claims require a choice rather than silently overwriting a target.
A chosen existing target takes the Host name, membership and occurrence order.
Incomplete references, unresolved Track matches and failed selected media retain
the existing Playlist. A source that changes after Review blocks only dependent
selected Playlists, allowing independent ones to proceed.

Library Sync Helper v7 records one-to-one pairs of the existing path-derived Host
Playlist identity and the persistent iPod Playlist ID. Readers retain v1–v6
compatibility. Resolve temporary draft IDs through the verified writer's identity
mapping, then publish associations only after successful Library publication.
An unchanged accepted match uses the existing verified no-op Library review before
atomic helper publication. Failed or skipped Playlists do not advance associations.
Explicit rebinding supersedes the earlier source or target claim; removed targets
are pruned when publishing the helper. Malformed helpers remain preserved.

Original iOpenPod used a path-derived managed Playlist identity. We retain cheap
source identity while keeping it separate from native Playlist identity. A title
or membership edit therefore keeps the saved target. A moved source can use a
unique name or an explicit match. Hashing Playlist contents would change identity
when the user edits its Tracks, and identical contents do not prove two Playlists
are the same. No content hash, dependency, or persistent selection rule is added.

## Verification

Pure planner, virtual-device and Qt tests cover title changes across helper reload,
one-to-one target selection, explicit creation, skipped and failed work, repeated
Track occurrences, unchanged-match publication, helper migration and corruption,
independent changed sources, keyboard checkboxes and bounded Review scrolling.
