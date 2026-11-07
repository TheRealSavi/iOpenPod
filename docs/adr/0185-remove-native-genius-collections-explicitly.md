# ADR-0185: Remove native Genius collections explicitly

- Status: Accepted
- Date: 2026-10-24
- Extends: ADR-0177 and ADR-0184

## Context

The Genius page now offers manual Mix creation, but it hides the existing Remove
button. Native Genius Playlists may live in the canonical Library, a saved plist
sidecar, or both. Mixes are SQLite containers, and iOpenPod's ownership document
may also record a Mix as manual or automatic. A remove action must cover the
selected native collection without treating its Tracks as deleted.

## Decision

The Genius page shows Remove for a selected Playlist or Mix and confirms the
selection before staging it in the Library Workspace. The selected collection
identity is checked against the loaded Active iPod during preparation. A canonical
Genius Playlist is explicitly omitted from the Library draft. A matching saved
Playlist sidecar is removed by Storage using its captured fingerprint. If both
represent the same native identity, one action removes both representations.

On a supported SQLite iPod, explicit Mix removal uses iPodDB's selective native
removal intent. It may target a Mix that was present before iOpenPod managed it;
the user selected that exact collection. Any matching ownership entry is removed
from the portable document in the same Storage transaction. Removing an automatic
Mix does not permanently lower the configured Count; the next Sync may fill the
vacated slot.

All removal intent is reversible until publication. Source preconditions,
transaction verification, recoverable deletion, and disconnect handling remain
those of the existing Library save. Mix removal is enabled only where the native
SQLite writer and device capabilities are confirmed. Unmentioned native
collections and Track media remain preserved.

## Consequences

The ordinary Playlist page continues to exclude native Genius Playlists from its
editing actions. The Genius page owns the explicit removal path. Saved sidecars
are selected by their parsed native identity or their numbered filename when no
native identity exists. Virtual device tests cover Mix ownership cleanup, saved
sidecar deletion and recovery, and the Genius page's confirmation and staging.
