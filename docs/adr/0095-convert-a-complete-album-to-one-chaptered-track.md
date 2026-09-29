# ADR-0095: Convert a complete Album to one chaptered Track

- Status: Accepted
- Date: 2026-09-29
- Extends: ADR-0026, ADR-0036, and ADR-0073

## Context

Original iOpenPod can combine an Album's Tracks into one encoded file with chapter
markers, then replace the source Tracks. This changes media bytes and Track
identities, so metadata-only editing cannot express the operation. iOpenPod 2.0
already has Prepared Media, explicit Track omissions, and a recoverable Library
Storage Transaction.

## Decision

The context action accepts every saved Music Track in one named Album, in disc and
Track-number order. It requires at least two Tracks and rejects an Album containing
existing chaptered Tracks. The Application Layer copies each source through the
Active iPod's identity-bound Storage session into temporary Host files. A background
worker measures each source, rejects changed duration or unsupported streams, and
uses FFmpeg to create one AAC file, or MP3 when only its encoder is available. The
output is inspected for Device Profile compatibility and duration before it enters
the Library Workspace. Chapter markers are recorded both in the media container and
as semantic Track chapters for iPodDB.

One revision-bound Library Draft adds the verified output, explicitly omits the
source Tracks, and replaces their Playlist occurrences with one occurrence at the
first source position in each Playlist. It retains the first Track's existing cover
reference and redirects Photo Album slideshow music references to the new Track.
The ordinary automatic or manual Library save policy applies. The
temporary Host output stays available while its draft resource is referenced;
reset, successful reload, disconnect, or shutdown releases it. A failed or cancelled
conversion leaves the Library Draft unchanged.

Library preparation captures source file preconditions and output content facts.
Storage publishes the new media and verified database generation before recoverably
removing unshared source files in the same transaction. This workflow does not use
the Original iOpenPod at runtime or require Backup Snapshots.

## Consequences

- The action is available only for a complete saved Music Album; partial selections
  and already chaptered Tracks need a different workflow.
- Conversion requires FFmpeg and FFprobe on the Host and enough temporary Host space
  for source copies and the encoded output.
- Existing Playlist duplicates from the converted Album collapse to one chaptered
  Track occurrence per Playlist. Reverting the draft restores the original entries.
- Source Tracks and their media remain intact until the reviewed transaction commits.
