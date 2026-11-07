# ADR-0201: Hide Genius Mixes without confirmed support

- Status: Accepted
- Date: 2026-10-27
- Amends: ADR-0184

## Context

ADR-0184 keeps the Genius Mixes section visible on every loaded iPod. This exposes
a heading and disabled management controls on devices that cannot play Mixes.

## Decision

Show the Genius Mixes section only when the Active iPod has confirmed native Mix
support. Unsupported and unknown capabilities hide the entire section, including
its heading, controls, and any captured Mix entries. The displayed collection count
and empty state reflect only visible collections. Captured data stays retained.

Supported iPods keep the section visible even when empty or unavailable for writing.
Settings and Add retain the existing writable-device and writer-capability checks.
Device changes and language changes rebuild the section using the current profile.

## Consequences

The sidebar shows Mix controls only on devices with confirmed native support.
Genius Playlist browsing continues to use its existing rules.
