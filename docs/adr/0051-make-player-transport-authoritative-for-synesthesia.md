# ADR-0051: Make Player transport authoritative for Synesthesia

- Status: Accepted
- Date: 2026-09-14
- Superseded in part by: ADR-0078's preparation of the next Playback Entry
- Supersedes in part: ADR-0042's explicit selected-file input boundary,
  ADR-0043's private Synesthesia playback session, and ADR-0047's private playback
  and page-annotation decisions

## Context

Synesthesia was first built as an isolated proof: its page selected a Host audio
file, ran complete-song analysis, and then played that file through a private Qt
Multimedia transport. The application Player paused before that second transport
started. The page also carried its own play control, seekable Section timeline,
analysis progress, source label, and musical annotations.

That proof duplicates the audio engine and divides transport authority. It can make
the Player disagree with the graphics, discards the active Playback Queue context,
and requires users to select a second copy of music that iOpenPod is already
playing. The integrated experience instead needs one audio owner, uninterrupted
playback during analysis, and graphics that join the current Track at the Player's
latest timestamp.

Whole-track analysis still needs a seekable local file because FFmpeg demuxers may
seek while opening formats such as M4A. An iPod Mount Point is not a safe long-lived
input: current Track reads must remain bound to the Active iPod's Filesystem
Session, Connection Generation, and media-file identity.

## Decision

`PlaybackController` and its `PlaybackBackend` remain the sole owners of audio
output and transport. Synesthesia may observe the current Playback Entry, position,
playing state, and explicit seeks. It may not pause, resume, stop, seek, restart, or
decode audio for playback, and it does not create another media player.

The Player exposes one Synesthesia action above the current Track's rating. The
action has no sidebar counterpart. Invoking it opens the internal Synesthesia page
and starts a fresh Musical Analysis Job for the current Playback Entry. While the
page remains active, a successor Playback Entry starts a replacement Job; metadata
reconciliation within the same entry does not. Leaving the page cancels and
releases its ephemeral analysis state without changing playback.

`SynesthesiaController` accepts a Track and an authorized
`PlaybackSourceProvider`. Its worker opens an independent, identity-bound
`PlaybackSource`, copies the encoded bytes to an application-owned temporary Host
file, analyzes that file, and removes it on success, failure, cancellation, or
stale completion. The copy is an implementation bridge for the existing
path-oriented analysis backend, not a Playback Source for audio output and not a
cache. No Track-derived artifact is retained.

The Synesthesia page contains only `SynesthesiaRenderer`; it has no file chooser,
transport, timeline, progress, source label, Section annotation, or analysis
readout. Process-wide status presentation may report analysis progress or failure
outside the visual field.

Player position updates advance the renderer normally. An explicit Player seek
starts a new Synesthesia Transport Epoch and relocates the renderer. When analysis
completes, the page first installs the Track Analysis, then relocates to the
Player's latest position in the current epoch, and finally mirrors the current
playing state. This exact relocation prevents the graphics from beginning at zero
after a long analysis. A stale Job can never publish into a replacement Playback
Entry.

## Consequences

- Playback continues through analysis, cancellation, navigation, renderer failure,
  and stale Job cleanup.
- Queue and History behavior stay under the existing Player and Playback Controller
  contract from ADR-0017.
- Synesthesia gains safe access to current Track bytes without receiving a Mount
  Point or sharing the Playback Backend's decoder or read handle.
- Complete-song analysis temporarily consumes Host storage approximately equal to
  the encoded Track size; cleanup is mandatory on every exit path.
- The visual field has one authoritative clock but may appear only after analysis
  finishes and relocates to the current timestamp.
- The analysis backend remains reusable and independent of transport or
  presentation policy even though its Qt-facing controller now accepts Tracks
  rather than user-selected Host paths.
