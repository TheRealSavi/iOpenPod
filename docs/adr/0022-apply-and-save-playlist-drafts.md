# ADR-0022: Apply and save Playlist drafts

- Status: Accepted
- Date: 2026-09-05
- Extends: ADR-0020 and ADR-0021

## Context

The user requested working Playlist and folder editing, Smart Playlist rules, and
physical saving. They explicitly chose to apply rules and matching saved Tracks
together. This supersedes ADR-0021's application behavior that retained membership
on a rule edit and stopped at Prepared for review. Preparation itself remains pure.

## Decision

The Playlist Workspace remains an application draft over immutable Library records.
Creating a Smart Playlist or changing its rules evaluates those rules against the
loaded Tracks and applies the configuration and resulting entries as one edit.
Surviving occurrences retain their identities. Renaming, moving, previewing, or
applying identical rules preserves saved membership. Unrelated Smart Playlists are
never automatically reevaluated. Live updating persists the iPod preference; it
does not start an application background reevaluation service.
An explicit Evaluate now action refreshes only the selected supported Smart
Playlist from the current Library draft and applies changed saved membership as a
reversible edit. Read-only imported rules cannot be evaluated by iOpenPod.

The semantic Smart Playlist contract owns shared validation and supported field
and operator descriptions. The application owns matching, while iPodDB privately
maps semantic conditions to native fields. Supported conditions include recursive
all/any groups, text, unsigned numbers, checkbox fields, absolute dates, relative
date periods, checked Tracks, limits, and selection order. Dates use Unix seconds;
the binary adapter applies the database timezone. Relative periods use positive
seconds. Unsupported imported conditions remain read-only, with their bytes and
saved membership retained. Unchanged supported conditions also retain their private
headers and payloads during a sibling or preference edit.

Regular Playlist membership can be extended by dragging selected Track occurrences
onto a regular Playlist in the sidebar. Drag data belongs to one unchanged
workspace revision; folders and Smart Playlists reject Track drops. Playlist pages
and sidebar context menus can remove the selected Playlist or folder from the draft.
Removing a folder also removes every nested Playlist and folder. Track-level Remove,
Move Up, Move Down, and Add Tracks page buttons remain absent.

Review Changes prepares and verifies output in the background. Save to iPod is a
separate explicit action on that exact review. The application coordinator accepts
only the review it issued for the current source. This commit workflow accepts
Playlist and folder changes with unchanged Tracks, ArtworkDB, media, and artwork
assets. It atomically replaces only iTunesDB. General multi-file Sync is still
disabled. Supported output remains unsigned or HASH58 iTunesDB; required unsupported
signatures and companion formats continue to block preparation.

During saving, workspace edits and device-selection operations are held. The
coordinator opens a temporary writable Filesystem Session for the captured Volume
and Connection Generation. It rechecks database fingerprints and signing identity
immediately before publication. All device-file operations remain inside Storage.

Storage's `replace_with_recovery` holds one Volume writer lease across verified
original retention, an intent journal, atomic replacement, verification, journal
completion, and flushing. Each attempt uses a unique directory beneath
`.iopenpod-recovery`. The original bytes and JSON journal remain after completion
or failure. They are operation recovery data, independent of user-controlled Backup
Snapshots. Temporary staging files are cleaned up when safe. Automatic recovery-copy
deletion is deliberately absent.

`restore_replacement` can restore a verified original over the exact recorded
replacement using an explicit current fingerprint. It refuses unrelated later
changes and corrupt recovery data. After a disconnect or failed verification,
reconnect and inspect the retained journal and current file before recovery;
recovery is not an automatic destructive repair. A recovery UI remains future work.

Only verified success adopts a reparsed source, publishes the saved Library, and
clears the draft. Allocated Playlist identities preserve current selection and
expanded folders. Failed saves retain the draft and grouped diagnostics; stale
results cannot replace a newer workspace. Cancellation is cooperative before
publication. Once publication starts, the worker finishes verification and reports
the actual outcome. A system flush limitation accompanies success as a warning
with safe-eject guidance.

## Consequences

The common Library API stays independent of Qt and Storage. The GUI does not pack
bytes or mutate device files. A narrow single-file commit can support useful
Playlist editing without prematurely implementing media import or a general Sync
transaction. Recovery copies consume space until explicitly managed. The writer
still preserves unsupported rules rather than claiming full iTunes evaluator
compatibility. Fixed Original iOpenPod rule bytes and virtual-device failure tests
provide evidence; they do not substitute for physical firmware testing.
