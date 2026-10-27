# ADR-0200: Skip unfinished Genius analysis during Sync

- Status: Accepted
- Date: 2026-10-27
- Extends: ADR-0183 and ADR-0199

## Context

Users can disable Genius generation before starting Sync, but may also want to
move past a long acoustic analysis after it has started. Completed profiles should
remain useful, and skipping optional work must preserve normal Sync cancellation
and source validation.

## Decision

The Sync progress view offers **Skip for this Sync** while preparing or analyzing
music for Genius. A request-scoped signal stops admitting audio work and interrupts
unfinished workers at their normal checkpoints. Completed worker results and cache
hits remain available to ranking and are saved through the existing Host cache.
Remaining Tracks use metadata candidates, and Sync continues normally. Prepared
Host profiles receive device cache associations only after verified publication.

Skipping does not change the saved Analyze for Genius setting. Every new Sync
starts with a fresh skip signal. Full cancellation, disconnected sessions, and
changed sources retain their existing failure and safety behavior. A skipped Track
does not produce an audio-unavailable warning merely because the user skipped it.

## Consequences

Users can shorten an in-progress Sync without discarding completed Genius work.
Later Syncs reuse those profiles and resume analysis of remaining Tracks. Ranking
uses the profiles available at the time of the skip, so recommendation quality can
differ from a fully analyzed Library.
