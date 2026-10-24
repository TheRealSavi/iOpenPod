# ADR-0184: Manage manual and automatic Genius Mixes

- Status: Accepted
- Date: 2026-10-24
- Extends: ADR-0126, ADR-0176, ADR-0177, and ADR-0178

## Context

The requested Genius sidebar has Settings and Add glyphs beside Genius Mixes.
Add presents multiple proposed Mixes; Settings controls how many automatic Mixes
to keep and how long they stay before replacement during Sync. Manual Mixes never
expire or consume automatic slots. Original iOpenPod's empty Genius writer,
documented in the existing format investigation, supplies no collection-management
policy to translate. Native Mix authoring is currently evidenced only for SQLite
artifact targets, even though some Classic firmware also supports Mix playback.

## Decision

The Application Layer owns a fixed catalog of broad genre families and normalized
genre aliases. Proposals use music in the desired Library and require at least ten
matching Tracks, consistent with the existing native minimum result count. Unknown
genres do not create new catalog entries. These are possible starting Tracks;
native Genius relationship traversal still determines playback, so genre purity
and playback on every supported firmware are not guaranteed.

The Genius Mixes section remains visible on a loaded iPod, including when empty.
Settings and Add are enabled only for writable devices with confirmed native
Playlist and Mix support and a supported SQLite writer. The Add dialog uses a
multi-selection grid and stages manual intent in the shared Library Workspace.
The existing automatic Library save applies it by default; the user's explicit
Draft all changes preference continues to defer publication. Stale dialogs,
disconnects, and locked workspaces cannot submit additions to another Library.

Settings saves Count and Expiry together through the existing portable iPod
settings workflow. Count defaults to zero (off); Expiry defaults to 30 days.
Sync and Refresh Library read the confirmed device settings and evaluate policy
against the completed desired Library. Count is bounded by catalog size and actual
availability. Reducing Count removes the oldest excess automatic Mixes; zero
removes all owned automatic Mixes at the next Sync. Existing collections from
other applications are never claimed by name or counted as automatic Mixes.

An automatic Mix expires only when its elapsed age is greater than Expiry. Random
selection excludes definitions currently present among managed Mixes, including
manual Mixes and the Mix being replaced. If no different eligible definition is
available, retain the expired Mix and its original age. Repeated Sync before
expiry preserves identity and age. Selecting an automatic Mix manually converts
it to permanent ownership without recreating its native container.

The bounded version-1 `iPod_Control/iOpenPod/genius-mixes-v1.json` document records
catalog keys, native container identities, and Unix addition times. A null time
means manual ownership. Missing state never authorizes deletion; malformed state
blocks management and remains untouched. Native collections missing from current
SQLite evidence lose their stale ownership records. The application captures
ownership, settings, and native collections with file preconditions. Ownership
changes and native artifacts are staged, verified, committed, and recoverable in
one Storage transaction. Preparation does not persist ownership or advance age.

iPodDB adds explicit selective Mix additions/removals alongside its existing full
replacement intent. Those forms cannot be combined. Unmentioned native Mix
containers, memberships, seeds, UI state, and Unknown Data retain the established
preservation path. The Application Layer owns all catalog, timing, ownership,
random-selection, and capability policy. No new dependency is introduced.

## Consequences

This extends ADR-0178's preservation-only collection policy and ADR-0177's browsing
UI. Ordinary Library saves do not rotate Mixes. Manual additions regenerate the
graph through the same bounded audio analysis and Storage publication path as
Sync. Genre proposals depend on usable genre tags. If too few eligible definitions
exist, the automatic count may remain below the requested value.

Validation covers catalog selection, ownership isolation, exact expiry boundaries,
random replacement, capacity limits, settings changes, cancellation, reconnect,
native Unknown Data retention, and rollback using virtual devices. Physical
acceptance of this collection-management workflow remains separate.
