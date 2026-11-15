# ADR-0268: Sync opt-in ListenBrainz recording feedback

- Status: Accepted
- Date: 2026-11-14
- Extends: ADR-0101
- Amended by: ADR-0269 for the shared Scrobble Ratings setting and Last.fm loved status

## Decision

An independent, default-off Sync behavior setting sends committed iPod music
ratings to the connected ListenBrainz account during manual scrobbling or the
enabled Sync scrobble step. Ratings 80/100 send Love (1); 20/40 send Hate (-1).
Other values send nothing and never clear remote feedback. Host tag Back Sync is
independent. Rating changes do not require new plays or usable playback dates.

Keep feedback observations and pending deliveries in version 3 of the existing
Host Scrobble Queue, under its lease and atomic Storage publication. Read older
versions without losing play cursors or Last.fm date reservations. Feedback has
independent receipts scoped to Volume Identity, persistent Track identity and
account. Acknowledging a listen never acknowledges feedback, or vice versa.
Unchanged observations do not resend; changed scores replace pending intent.
Neutral ratings cancel unsent intent without deleting remote feedback. Disabling
the setting pauses capture and delivery; disconnecting an account retains its
pending work. Captured work survives Track removal.

Prefer one valid MusicBrainz recording ID from embedded tags, read through bounded
Storage-backed media access. A MusicBrainz release-track ID is not a recording ID.
Absent, conflicting or malformed identifiers fall back to authenticated
ListenBrainz artist/title lookup. Persist resolved recording IDs before posting.
No-match results are skipped for that observation; service failures remain pending.
Only positive acknowledgements settle delivery. Observe rate limits and persist
acknowledgements even if cancellation arrives during a request.

## Consequences

Enabling the setting captures existing rated Music and Music Video Tracks with
persistent identity and artist/title, including Tracks with no new plays. The
queue records the effective Love/Hate observation, not every star edit within a
range. A later neutral observation permits a subsequent explicit rating to be sent
again. Local receipts do not reconcile later website edits or other Hosts, and
retries after uncertain acceptance may repeat the same idempotent feedback.
Lookup is service-provided matching evidence, not proof of recording identity.
No source-media tags or iPod files are written by feedback capture or delivery.
