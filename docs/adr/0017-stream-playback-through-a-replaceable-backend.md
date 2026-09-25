# ADR-0017: Stream playback through a replaceable backend

- Status: Accepted
- Date: 2026-08-31

## Context

iOpenPod needs actual audio playback from the Active iPod without coupling Player
widgets, Playback Queue and History policy, or device access to one decoder library.
Qt Multimedia is already present through PySide6 and provides the cross-platform
decoder, transport clock, and audio output needed now. A future platform-specific or
specialized backend must remain possible without rebuilding the GUI or runtime
playback model.

The media files are on removable storage governed by Storage safety rules. Passing a
Mount Point or absolute Host path to a decoder would bypass the identity-bound
Filesystem Session and could continue reading from a reused path after disconnect or
reconnection. Materializing every Track as a complete in-memory buffer or temporary
Host file would preserve the boundary but add avoidable latency, memory or disk use,
and cleanup work.

## Decision

The Application Layer defines a typed Playback Backend boundary. The
`PlaybackController` owns current-Track selection, Playback Queue and Playback
History policy, and transport intents. It delegates start, play, pause, stop, seek,
and volume operations to the backend and treats the backend's playing-state,
position, completion, and failure events as authoritative.

`QtPlaybackBackend` is the production adapter. It privately owns `QMediaPlayer`,
`QAudioOutput`, and a random-access `QIODevice` bridge. Qt Multimedia is an
implementation detail behind the Playback Backend interface; GUI widgets and
playback models do not import it.

Every backend start receives a monotonic runtime Playback Attempt identity. All
state, position, completion, and failure events report that identity, and the
controller accepts events only from its active attempt. Track identity alone is
insufficient because the Playback Queue permits duplicate occurrences and Qt can
deliver events that were queued while an earlier source was being replaced.

A backend starts a Track from a seekable, read-only Playback Source rather than a
Mount Point, absolute Host path, or complete byte copy. `DeviceCoordinator` resolves
the Track against the authoritative Active iPod Library, validates its Device Path
beneath `iPod_Control`, captures its source file identity, and supplies bounded range
reads through the Active iPod's Filesystem Session. Reads fail closed if the Active
iPod, Connection Generation, or source identity changes.

Playback Queue, Playback History, current Track, transport position, playing state,
and volume remain runtime-only application state.

## Consequences

- Another decoder and audio-output implementation can replace Qt without changing
  the Player, Queue and History models, or transport policy.
- Qt Multimedia can seek and decode directly from the Active iPod without exposing
  device paths or materializing a whole Track on the Host.
- Every source range remains subject to Storage session and identity validation;
  this adds small per-read coordination overhead.
- Supported codecs and output behavior depend on the Qt Multimedia runtime shipped
  for each Host platform. Unsupported, corrupt, or protected media can fail and must
  be reported as an Application Layer playback error.
- The Python `QIODevice` bridge and Qt signal translation are isolated inside the Qt
  adapter and require focused integration tests.
- Playback Attempt identities add a small amount of protocol state, but prevent a
  delayed decoder event from mutating the Track that succeeds it.
