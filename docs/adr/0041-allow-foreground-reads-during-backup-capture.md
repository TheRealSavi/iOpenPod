# ADR-0041: Allow foreground reads during Backup capture

- Status: Accepted
- Date: 2026-09-13
- Extends: ADR-0011, ADR-0017, and ADR-0039

## Context

A Backup capture is a long-running, read-only Device-to-Host workflow. The initial
controller treated it like Restore and reserved the Active iPod through the same
exclusive busy state used by mutation workflows. The read-only Backup Session also
retained the Device Coordinator's state lock for the complete capture. Foreground
artwork and Playback Source range reads need that lock briefly to validate the
Active iPod, so they could remain blocked until the complete backup finished.

Allowing device mutations during capture is not safe. Incremental reuse and the
final metadata rescan assume that iOpenPod does not change the source tree while it
is capturing it. Changing the Active iPod must also remain unavailable because a
capture is tied to one identity-bound Filesystem Session and Connection Generation.

## Decision

Backup capture uses a read-only Active iPod reservation. The reservation keeps the
selected connection stable and prevents every participating Application Layer
device-mutation workflow from starting, but it does not put the Device Controller in
its general busy state. Read-only browsing, artwork loading, Library preparation,
Host export, and playback remain available.

The Device Coordinator captures and validates the Active iPod under its state lock,
then releases that lock before yielding a read-only Backup Session. The retained
Filesystem Session continues to fail closed on disconnect, Connection Generation
change, or file replacement. Foreground reads may therefore acquire the coordinator
lock briefly and issue independent Storage range reads while capture is streaming.

Restore and Restore Recovery retain the existing exclusive reservation because they
mutate device content and can temporarily require a Library reload or explicit
recovery. Active iPod discovery and selection remain blocked during either kind of
reservation.

No fixed bandwidth split is promised. Backup copies remain chunked, and the Host
operating system schedules concurrent reads. If physical-device testing still shows
foreground starvation after removing the long-held lock, read prioritization or
pacing must be added behind a generic Storage interface and driven by measured
latency rather than GUI or iPod-specific policy.

## Consequences

Playback and other read-only workflows can continue during a Backup capture without
weakening Connection Generation checks or permitting iOpenPod writes. Callers that
can mutate the Active iPod must acquire the Device Controller's exclusive
reservation, while long-running read-only workflows can acquire its read-only
reservation.

The Device Controller now exposes write availability separately from general busy
state. GUI adapters can keep read-only navigation usable while disabling mutation
actions. Backup correctness still detects external changes through per-file identity
checks and the final metadata rescan; iOpenPod cannot prevent unrelated Host
processes from changing a mounted device.
