# ADR-0027: Restore the previously selected iPod

- Status: Accepted
- Date: 2026-09-09

## Context

The Device Picker gives each Device Candidate an identifier scoped to its current
Connection Generation. That identifier correctly prevents stale filesystem access,
but it changes after a reconnect or application restart and therefore cannot identify
the user's previous choice in global settings.

iOpenPod should automatically load the previously selected iPod when it is connected
at startup. This restoration must not select a different iPod, weaken selection-time
validation, or add a visible preference.

## Decision

- After a Device Candidate successfully becomes the Active iPod, iOpenPod stores its
  stable Volume Identity in the global `devices/last-selected-volume-id` setting.
- Device Candidate IDs remain connection-scoped and are never persisted.
- When discovery completes without an Active iPod, iOpenPod automatically runs the
  ordinary selection workflow only when exactly one ready Device Candidate has the
  remembered Volume Identity.
- A missing, unready, or duplicate match leaves no Active iPod. The remembered value
  is retained so a later reconnection can restore it.
- Automatic restoration repeats the same identity, database, Filesystem Session, and
  Device Metadata Reconciliation checks as a selection made through the Device
  Picker. A failed restoration is reported as a normal selection failure.
- Selecting another iPod successfully replaces the remembered Volume Identity.
- This behavior has no visible setting or separate UI control.

## Consequences

The user's usual iPod loads automatically across application restarts and Connection
Generations without persisting a Mount Point or stale authorization token. Hosts with
no exact ready match remain in the normal no-Active-iPod state. Cloned or otherwise
duplicate Volume Identities fail closed instead of choosing an arbitrary candidate.

The global settings schema now contains one device-selection value, while device-
specific settings that travel with an iPod remain a separate future workflow.
