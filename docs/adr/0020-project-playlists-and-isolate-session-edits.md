# ADR-0020: Project Playlists and isolate session edits

The editor and persistence scope is subsequently extended by
[ADR-0022](0022-apply-and-save-playlist-drafts.md).

- Status: Accepted
- Date: 2026-09-05

## Context

The Playlist browser needs ordered Track occurrences, Smart Playlist rules, nested
Playlist Folders, and the iPod's name. iTunesDB can contain mirrored Playlist
datasets, firmware category records, and folder aggregation rules. Exposing those
records directly would duplicate user playlists and make the GUI interpret binary
format details. Device-writing workflows remain incomplete.

The Original iOpenPod's `docs/research/ipod-playlist-datasets.md`,
`src/iopenpod/itunesdb_shared/playlist_kinds.py`, `playlist_hierarchy.py`,
`playlist_properties.py`, and `mhod_defs.py` establish the behavioral baseline.
They are research references, never runtime dependencies.

## Decision

Extend the common immutable Library Snapshot with semantic Playlists and a device
name. iPodDB selects dataset 3 when present, including an empty dataset, otherwise
dataset 2. Dataset 5 contains firmware categories and does not supply the name or
sidebar entries. Selecting one dataset for presentation is an iOpenPod 2.0 policy;
the lossless Database Document still retains all datasets.

Exactly one eligible Master Playlist supplies the device name. The Master Playlist
is not a user-editable sidebar item. Without an unambiguous name, Active iPod
presentation keeps its existing candidate-name fallback.

The projection preserves stored Track order and repeated occurrences, skipping
unresolved references and podcast grouping rows. Folder classification precedes
smart-rule classification. Invalid parents and cycle members detach to the sidebar
root in the read projection only. Unique opaque Playlist identities, like Track
identities, are required by the common contract. Duplicate canonical identities
fail explicitly rather than resolving unpredictably.

Smart Playlist configuration is separate from saved Track membership. The semantic
contract retains nested groups and marks unsupported source conditions uneditable.
Browsing never reevaluates imported membership. The first session editor supports
flat groups over title, artist, album, genre, year, rating, and play count, with
checked-track and limit preferences. Unsupported or nested imported configurations
can be renamed and moved, but their rules cannot be replaced by this editor.

The Application Layer owns a Playlist Workspace for one Active iPod. Creation,
renaming, descriptions, manual membership and ordering, smart-rule previews, and
folder moves change immutable session drafts. The GUI states that these changes
are not saved to the iPod. Switching or disconnecting an iPod clears drafts; modal
edits and drag data carry session/revision checks. Folder ancestry and traversal
are iterative, with no application depth limit and explicit cycle rejection.

## Consequences

The browser presents music and organization without raw flags, IDs, or Chunk data.
Database parsing and lossless serialization remain inside iPodDB. Device persistence
continues to require semantic-to-document edits and the Storage transaction workflow;
the draft records are not a second database writer model.

Draft changes are lost when the session ends. Smart preview evaluation is deliberately
limited and does not claim full iTunes or firmware evaluator compatibility. Future
write support must reconcile both Playlist datasets, rebuild folder aggregation,
preserve unsupported rules, and validate firmware-specific behavior before committing.
