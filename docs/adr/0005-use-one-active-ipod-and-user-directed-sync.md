# ADR-0005: Use one Active iPod and user-directed Sync

- Status: Accepted
- Date: 2026-08-20

## Context

The Original iOpenPod discovers connected iPods, lets the user choose one in a
Device Picker, and loads one selected device into the application. Its Sync behavior
is primarily Host-to-iPod but includes useful iPod-to-Host operations. It also offers
backup and restore without making every Sync depend on a mandatory backup policy.

iOpenPod 2.0 needs the same operating model stated independently of GUI widgets and
worker implementation details.

## Decision

- Storage may discover multiple connected candidates, but the user selects one
  Active iPod through the Device Picker.
- iOpenPod loads and operates on at most one Active iPod at a time.
- Selecting another iPod invalidates the previous Filesystem Session, clears
  device-scoped state, and creates a new Connection Generation for the new selection.
- Sync is primarily Host-to-iPod and proceeds through a user-visible Sync Plan and
  Sync Review.
- Supported iPod-to-Host behavior includes Back Sync of ratings and other supported
  metadata, exporting iPod-only Tracks, and exporting images.
- iOpenPod provides Backup Snapshot and restore workflows. The user may configure an
  automatic Backup Snapshot before Sync, ask before Sync, or continue without a new
  snapshot. Backups remain the user's responsibility.
- Long-running work reports progress, does not block the GUI thread, and supports
  cancellation where stopping is safe.
- If the Active iPod disconnects, its Filesystem Session becomes invalid and iOpenPod
  stops issuing operations. iOpenPod reports that interrupted work may be incomplete
  and requires reconnection or a new selection before continuing. It does not promise
  rollback while the Volume is physically absent.

## Consequences

- Application state does not need to support concurrent editing of several iPods.
- Discovery results and the Active iPod are distinct concepts.
- Host-to-iPod Sync does not erase intentional export and metadata write-back
  features.
- Storage validation, verification, and recovery rules apply whether or not the user
  creates a Backup Snapshot.
- Cancellation is cooperative and safety-aware rather than an arbitrary termination
  of a worker during a device mutation.
