# ADR-0060: Use Native Safe-Removal Services

- Status: Accepted
- Date: 2026-09-15
- Extends: ADR-0002, ADR-0011, and ADR-0027

## Context

The Sidebar has an Eject placeholder, but flushing application writes or removing a
mount alone cannot establish that a Physical Device is safe to unplug. Other
processes, sibling Volumes, filesystem caches, drivers, and hardware caches remain
under Host control. The three supported operating systems expose different native
safe-removal contracts and different refusal information.

An eject can also partially succeed: the filesystem may be unmounted before a later
physical eject or power-off request fails. Treating that state as either a connected
Active iPod or confirmed safe removal would be incorrect.

## Decision

- Safe eject is a Storage operation over an exact, revalidated Mounted Volume and
  Connection Generation. The GUI never receives a Mount Point or native device
  handle.
- Windows matches the retained physical disk number to a present disk device
  interface, resolves its removable parent with `CM_Get_Parent`, and calls
  `CM_Request_Device_EjectW` on that parent. Plug and Play veto type, veto name, and
  Configuration Manager result are preserved in the user-facing failure.
- macOS uses the Disk Arbitration-backed `diskutil` client to unmount the validated
  whole `diskN`, then eject it. Both operations are unforced and separately checked.
- Linux calls UDisks2 over the system D-Bus. It resolves the selected block device,
  requires `CanPowerOff`, refuses known cross-Drive sibling effects, unmounts all
  mounted filesystems on the Drive without force, then calls `Drive.PowerOff`.
- No adapter uses force, a raw USB reset, bare unmount, or a media-eject IOCTL as a
  successful substitute for the native safe-removal confirmation.
- The Application Layer stops playback and closes its Filesystem Session before the
  request. A pre-unmount refusal reopens the same retained generation. Success or a
  partial unmount expires the generation and removes every candidate on the
  Physical Device.
- Native failures are translated into actionable messages. Success is shown only
  after the OS confirms safe removal. Partial failure explicitly states that
  filesystem access ended but physical removal was not confirmed.
- Eject is serialized with other Active-iPod operations. The button is disabled
  during background work and read reservations, and unsaved Library Drafts require
  explicit discard confirmation.

## Consequences

Users receive a truthful safe-to-disconnect confirmation and can correct retryable
busy, open-file, or authorization failures without reloading the iPod. A partially
unmounted connection cannot be reused accidentally.

Windows safe removal depends on Configuration Manager and SetupAPI identity
matching. macOS depends on the system `diskutil` Disk Arbitration client. Linux
depends on UDisks2 and may invoke the desktop authorization agent. If an exact native
target or safe power-off relationship cannot be established, iOpenPod fails closed
and directs the user to the operating system's safe-removal control.

The rationale and primary operating-system references are recorded in
`docs/research/safe-native-eject.md`.
