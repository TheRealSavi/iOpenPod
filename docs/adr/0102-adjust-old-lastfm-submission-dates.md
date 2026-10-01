# ADR-0102: Adjust old Last.fm submission dates

- Status: Accepted
- Date: 2026-10-01
- Amends: ADR-0101

## Decision

At the user's request, pending Last.fm deliveries older than its 14-day backdating
window receive distinct submission timestamps on the Host's current local calendar
day, no later than the captured current time. Oldest plays receive the earliest
available timestamps, one second apart where available. Existing pending timestamps
and previously allocated seconds for that account are not reused. If there are too
few elapsed seconds today, remaining plays stay pending until a later attempt.
ListenBrainz retains original dates. Missing or uncertain playback evidence still
does not qualify for capture.

The Scrobble Queue stores the original estimated playback start and a separate
optional submission timestamp. Both the adjustment and the account's allocation
watermark are persisted before contacting either service. Retries reuse the saved
date while it remains eligible, including across app restarts, Track removal, and
uncertain responses. A saved adjustment that itself ages beyond the window is
adjusted again. Original Library dates and iPod counters are never rewritten.
Version-1 queue state is read without losing cursors and saved as version 2.

## Consequences

Last.fm displays these plays on the adjusted date, rather than their original
playback date. Manual and Sync reports state the adjustment and show both date
ranges. Adjustments are informational; actual rejected deliveries remain pending
and are warnings. Only positive service acknowledgements remove deliveries.
The original estimate remains in the pending queue until acknowledgement, not in
a new permanent listening-history archive. Last.fm's acknowledgement matching uses
the submitted timestamp. This policy changes dates deliberately and does not
guarantee acceptance or exactly-once delivery after an uncertain response.
