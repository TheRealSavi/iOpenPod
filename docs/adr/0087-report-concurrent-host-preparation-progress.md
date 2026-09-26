# ADR-0087: Report concurrent Host preparation progress

- Status: Accepted
- Date: 2026-09-26
- Extends: ADR-0076 and ADR-0084

## Context

Sync prepares independent Tracks concurrently, but its progress messages identified
only the most recently active item. The GUI replaced that item on each update,
making concurrent work appear sequential. Conversion and decode verification
reported their start and completion without FFmpeg's measured progress.

## Decision

Storage consumes FFmpeg's documented `-progress pipe:1` protocol for conversion and
decode verification. It publishes typed output-time and speed samples on the tool
caller's thread while the process runs. Each progress record is bounded, and only
the latest sample is retained. Diagnostic output, cancellation checkpoints,
deadlines, and process reaping retain their existing protections. An FFmpeg end
record never authorizes publication or replaces output verification.

The Application Layer reports immutable snapshots of all currently running Track
preparations, keyed by Host source identity rather than display title. Worker
samples are coalesced and leave the active snapshot on success, failure, or
cancellation. Waiting and completed work are separate from active preparations.

The GUI gives each active Track its own action and progress bar. Conversion and
verification percentages use measured output time divided by the relevant media
duration. Percentages apply to the current phase and reset on a phase change;
verification still follows a completed conversion. Missing duration or measurements
produce indeterminate progress rather than an invented percentage. Aggregate
progress continues to count processed Tracks, including skipped Tracks.

## Consequences

Concurrent work stays visible without changing Sync concurrency or device
publication. Long-running conversions and verification can report useful activity
before a Track finishes. These measurements do not promise a preparation-wide
percentage or time estimate, and file capture and metadata work remain
indeterminate. No dependency is added. Progress identities confer no filesystem
authority, and lower-level Storage remains unaware of Tracks or iPods.
