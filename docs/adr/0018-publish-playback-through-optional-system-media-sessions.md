# ADR-0018: Publish playback through optional system media sessions

- Status: Accepted
- Date: 2026-08-31

## Context

The Host can expose dedicated media keys and a system Now Playing surface outside
iOpenPod's window. macOS provides MediaPlayer Now Playing and remote-command APIs,
Windows provides System Media Transport Controls, and Linux desktops commonly
consume the MPRIS D-Bus interface. iOpenPod should publish Track metadata and
runtime transport state to those facilities and accept their play, pause, seek,
Previous, and Next intents.

This integration must remain independent of the Playback Backend selected by
ADR-0017. A Playback Backend decodes a Playback Source and reports authoritative
engine events; a Host media facility neither decodes audio nor owns Queue, History,
or device access. Putting native Now Playing APIs in `QtPlaybackBackend` would bind
them to one decoder implementation and could allow system commands to bypass
`PlaybackController` policy.

Native media APIs also differ in lifetime, callback threads, window-handle
requirements, metadata formats, and availability. Their absence or failure must not
make local playback unusable.

## Decision

The Application Layer defines a typed System Media Session boundary beside, rather
than inside, the Playback Backend boundary. `SystemMediaBridge` observes only
authoritative `PlaybackController` state and publishes immutable System Media
Snapshots containing the current Playback Entry identity, Track metadata,
duration, position, playback state, available transport capabilities, and optional
album artwork. Artwork is an immutable, bounded RGB888 payload with dimensions and
a stable cache key; it is neither a GUI image nor a native Host object.

Native commands enter the bridge as typed transport intents. The bridge marshals
them onto the Qt application thread and calls idempotent controller operations such
as `play`, `pause`, `seek`, `previous`, and `next`. Native adapters never call a
Playback Backend, inspect a Playback Source, or access an Active iPod directly.

System media integration is optional and fail-open. Unsupported Hosts use a null
session. Failure to import, initialize, publish to, or close a native integration is
reported through application logging and must not interrupt audio playback. The
session clears Host Now Playing state when there is no current Track and during
orderly application shutdown.

Position publication is coalesced while playback is progressing and sent
immediately for Track, playing-state, and explicit seek changes. Native callback
registrations are retained for the session lifetime and removed during close.

Platform adapters use the Host's established facility:

- macOS uses `MPNowPlayingInfoCenter` and `MPRemoteCommandCenter` through the
  conditionally installed `pyobjc-framework-MediaPlayer` binding;
- Windows uses manual System Media Transport Controls obtained for iOpenPod's
  top-level window through `ISystemMediaTransportControlsInterop`;
- Linux will expose `org.mpris.MediaPlayer2` and
  `org.mpris.MediaPlayer2.Player` on the desktop session bus.

The macOS, Windows, and Linux adapters consume the same System Media Session
contract and do not alter the Playback Backend interface. The Windows adapter
obtains manual System Media Transport Controls for the application's top-level
window and uses the modular PyWinRT bindings. The Linux adapter owns
`org.mpris.MediaPlayer2.iOpenPod` on the desktop session bus through Qt D-Bus,
publishes the required root and Player interfaces, and uses the runtime Playback
Entry identity for MPRIS Track IDs. MPRIS uses microseconds, so the adapter converts
at the System Media Session boundary. Its `mpris:artUrl` points to at most one
session-scoped PNG conversion at a time.
`SystemMediaBridge` requests the current Track's cover through `ArtworkController`,
using the existing generation-scoped, byte-bounded artwork pipeline. It publishes
the result only while its artwork ID still matches the current Track. Native
sessions cache their converted Host artwork by the Application Layer cache key and
may not depend on GUI `QImage` or `QPixmap` objects.

## Consequences

- Media keys and Host Now Playing surfaces can control iOpenPod without coupling
  them to Qt Multimedia or a future audio engine.
- System commands follow the same Queue, History, retry, seek-bounding, and stale
  Playback Attempt policy as in-window controls.
- Platform adapters can be tested against the common snapshot and command contract,
  while real integration still requires validation on each Host.
- macOS and Windows distributions gain conditional native-media dependencies;
  other platforms do not install or import them.
- The Windows adapter requires a top-level native window handle during composition,
  while macOS and Linux do not.
- Host media presentation is best-effort and platform-controlled; iOpenPod cannot
  require every desktop shell to display every published field.
- Album artwork reuses the existing bounded RGB cache and adds at most one cached
  native conversion in each System Media Session.
