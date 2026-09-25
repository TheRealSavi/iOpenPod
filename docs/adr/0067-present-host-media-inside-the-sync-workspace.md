# ADR-0067: Present Host media inside the Sync Workspace

- Status: Accepted
- Date: 2026-09-18
- Supersedes: the normal-sidebar source choice in ADR-0064 and the direct Review
  transition in ADR-0066
- Extends: ADR-0005, ADR-0057, ADR-0063, ADR-0065, and ADR-0066

## Context

The Host Media Library exists to choose the desired contents of one Sync. Exposing it
as a second persistent Library Source in the normal application sidebar made it look
like a peer of the Active iPod, separated folder configuration from selection, and
sent a completed comparison directly to a read-only Review. That path provided no
place for the user to select Host media before the final plan was derived.

The Host browser still needs source isolation and the mature search, sort, list, grid,
and collection behavior of the iPod browser. Sync selection must not mutate a scanned
Library Snapshot or the initial comparison, and an unchecked item must have an
unambiguous meaning.

## Decision

Sync with Host first opens the modal media-folder dialog. Accepting the dialog
persists the staged folder configuration, starts the Host Media Scan, and opens a
staged **Sync Workspace** that replaces the main window's normal central content for
the remainder of the workflow. Canceling the dialog leaves the normal application
surface unchanged. The normal sidebar remains iPod-focused and has no Host Media
Library source choice. The workspace contains Sources, Select Media, Review, and
reserved Sync stages; scanning progress is shown inside that surface rather than in
a modal progress dialog.

Sources begins with folder configuration in the modal dialog and continues with scan
progress in the Sync Workspace; the folder editor is not embedded as a full page.
After the Host and iPod Media Scans complete, Select Media lazily creates
source-isolated instances of the existing Library pages and models. The Host
Workspace remains read-only, device actions and dragging are disconnected, and only
pages compatible with the Active iPod are shown. Its Track and Album views use a
Host-owned lazy artwork controller and cache; Host artwork identities are never sent
to the Active iPod artwork loader.

A mutable **Sync Selection** is layered over the immutable scan comparison:

- safely correlated Host items start selected because they are already on the iPod;
- Host-only items start unselected;
- Track rows, Album cards, collection cards, and Photo cards expose the shared
  circular checkbox presentation used by Photo Album membership;
- Album, collection, and Photo grids can group Selected, Mixed, and Deselected items;
- deselecting a correlated Host item requests removal from the desired iPod contents;
- selecting a Host-only item requests addition; and
- iPod-only items do not appear in Host selection. They appear in Review as optional
  removals and start unchecked.

Review derives an immutable selected Sync Plan from that mutable intent. Unsafe
correlations remain visible as Needs attention and never become authorized changes.
Changing the Active iPod exits and clears the Sync Workspace. Sync execution remains
disabled until the analyze, validate, execute, verify, commit, and cleanup workflow
is implemented.

## Consequences

Host browsing now has workflow context without weakening source isolation or
duplicating the Library browser. Folder configuration remains a contained modal
choice, while progress, media selection, and Review form one reversible full-window
flow. The meaning of every default is explicit: existing correlations are retained,
new Host media is opt-in, and removal of iPod-only media is also opt-in.

The application owns an additional mutable selection model, but scanned snapshots
and comparison plans remain immutable. Playlist reconciliation, Sync execution, and
publication are still future work. The Sync Workspace must remain honest about that
boundary and may not enable its final Sync action until execution exists.
