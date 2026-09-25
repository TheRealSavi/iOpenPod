# ADR-0078: Prepare the next Synesthesia Playback Entry

- Status: Accepted
- Date: 2026-09-25
- Supersedes in part: ADR-0051's fresh analysis on every successor Playback Entry

Starting whole-track analysis only when playback advances leaves the beginning of
each song in Synesthesia Preview. While the Synesthesia page is active, prepare
the Player's next Playback Entry behind the current Musical Analysis Job on the
existing single worker. The Playback Controller identifies that entry using its
normal Next policy, including forward History before the Playback Queue.

Retain only the current Track Analysis and one prepared result in runtime memory.
When the prepared entry becomes current, promote its completed result or unfinished
Job rather than analyzing it again. Matching requires the Playback Entry identity,
Track, and analysis request. Queue edits replace obsolete preparation; leaving
Synesthesia or clearing the playback session cancels and releases both analyses.
Coalesce model notifications until a playback transition settles so consuming a
prepared queue entry cannot invalidate its Job before promotion.

Preparation uses the existing independent, identity-bound Playback Source and
temporary Host file cleanup. It never controls transport, publishes progress or
failure for another song, or persists Track-derived data. A failed preparation
retries only when that entry becomes current or a new preparation is requested.
Serial analysis limits CPU and temporary-file pressure; rapid skips can still
reach a song before analysis is ready, so Synesthesia Preview remains necessary.
