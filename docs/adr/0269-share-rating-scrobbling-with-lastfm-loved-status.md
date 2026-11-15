# ADR-0269: Share rating scrobbling with Last.fm loved status

- Status: Accepted
- Date: 2026-11-14
- Extends: ADR-0101, ADR-0268

## Context

Last.fm supports Love and Unlove through authenticated artist/title requests.
Unlove removes a loved status; it is not ListenBrainz's Hate assignment. The user
requested one default-off **Scrobble Ratings** setting for both services, with
4-5 stars mapping to Love and 1-2 stars mapping to Last.fm Unlove or ListenBrainz
Hate. Separate service toggles would not match that choice.

## Decision

Replace the ListenBrainz-only preference with `sync/scrobble-ratings`, retaining
the existing per-iPod override and manual/Sync entry points. Three stars, unrated
Tracks and unknown native values leave remote status unchanged and cancel unsent
intent. The setting is independent of Host-file rating Back Sync. Each run uses
the setting captured before its worker starts.

Use **Rating Feedback** for the shared queued observation; reserve **Recording
Feedback** for ListenBrainz's recording assignment. The stored score describes
the observed rating range: 1 means Love, while -1 selects Last.fm Unlove or
ListenBrainz Hate according to the account's service. Last.fm uses artist/title
directly and never reads media tags or looks up MusicBrainz IDs for this work.

Queue version 4 accepts both services with independent account, Volume Identity
and persistent Track receipts. Versions 1-3 remain readable with their existing
play cursors, date reservations and ListenBrainz receipts. Last.fm observations
cannot carry a recording MBID. Pending work survives removal, restart and account
disconnection; turning the shared setting off pauses both services. A failed
service does not replay another service's acknowledged feedback or listens.

Use the existing Last.fm session and signed POST transport. Select XML for these
empty write responses and require the documented `<lfm status="ok">` envelope,
bounded by the existing response limit with DTDs rejected. Missing or failed
acknowledgements retain pending intent. Existing pacing and cancellation checks
apply; received acknowledgements are saved before stopping after interruption.

## Consequences

Enabling the setting submits existing eligible ratings to every connected account,
even with no new plays. A low rating can remove a Love set through Last.fm's website
or another application. Local receipts suppress unchanged observations but do not
reconcile later website edits or other Hosts. Retrying an uncertain response may
repeat the same idempotent Love/Unlove request. No new dependency or device mutation
is needed. See [Scrobbling](../scrobbling.md#scrobble-ratings) for API references.
