# Scrobbling

Use **Settings → Sync → Scrobbling accounts** to connect Last.fm, ListenBrainz, or
both. **Scrobble during Sync** defaults on for connected accounts. Switch it off
to submit only through **Maintenance → Scrobble now**. With no connected account,
the Maintenance action opens Sync settings and Sync does no network scrobbling.

## Connect services

- **Last.fm:** obtain an application API key and shared secret through **Get API
  key**, enter them, and choose **Sign in with Last.fm**. Authorize iOpenPod in your
  browser, return to the application, and choose **Finish signing in**. There is no
  bundled Last.fm application key. An expired authorization can be restarted with
  **Sign in with Last.fm**.
- **ListenBrainz:** use **Get user token** to open your ListenBrainz settings, copy
  the user token, and choose **Connect ListenBrainz**. iOpenPod validates the token
  and displays the account it belongs to.

Credentials are saved in the native OS keyring; an unavailable or locked keyring
must be enabled/unlocked to connect. Disconnect removes the local credentials and
stops submissions to that account. It does not revoke the service-side grant or
delete already submitted listens. No password is stored by iOpenPod.

## Submission and retry

Device selection first reconciles firmware Playback Sidecars into the committed
Library. Scrobbling then captures eligible music plays in a durable Host queue,
before any network submission or Sync removal. Network errors leave the queue
available for the next manual attempt or enabled Sync. Cancellation stops between
requests; an in-flight request can still be accepted. Completed acknowledgements
are saved before stopping. The status bar provides a cancellation action during
manual submission, and Sync shows its own Scrobble plays step.
Submission progress counts processed plays or ratings for the current service,
with a determinate progress bar in Sync and the manual status display. Counts
advance after queue persistence, including the final batch or rating. Rejected
plays and unmatched ratings count as processed; accepted and pending deliveries
remain separate in the result report. Capture stays indeterminate until delivery
totals are known, and changing service or work type starts a new progress phase.
Manual results keep the status bar short: **Details** opens a scrollable, copyable
report. **View last scrobble report** in Settings → Sync reopens the most recent
manual report for the current application session.

Each service/account has independent cursors and pending entries. The Library's
**Unscrobbled Plays** column continues to reflect the iPod's aggregate counter; it
is not an account delivery status and is not reset by this workflow. Submission
results report accepted account deliveries, pending account deliveries, and skipped
Tracks, plus adjusted Last.fm dates when applicable. A play delivered to both
services counts as two accepted deliveries.

Tracks without artist/title, usable dates, or persistent identity are skipped, as
are non-music Tracks and Tracks of 30 seconds or less. Repeated-play timestamps are
estimates from the retained last-played time and duration. Service rejections remain pending. The
report identifies each submitted artist, title, and album, with the service's
rejection code and explanation when supplied. Repeated rejections of the same
Track and reason are grouped across batches with a listen count and estimated
playback date range in UTC. Accepted listens are excluded from this list. Service
messages are bounded plain text with credentials redacted.

Date defects alone do not block Library Sync. Saved queue dates preserve integer
evidence, including signed values; malformed optional dates become missing. Queue
identities and capture cursors remain validated. Unusable submission dates stay
pending, and an unrepresentable Host calendar defers Last.fm adjustment until a
later attempt. See [ADR-0240](adr/0240-treat-calendar-dates-as-best-effort-metadata.md).

Last.fm submission dates older than its 14-day backdating window are automatically
moved to **today**, using the Host's local calendar. Each receives a distinct second
no later than the current time; oldest plays receive earlier seconds. The queue
saves these dates before sending and reuses them on retries while still eligible.
If today's elapsed seconds are exhausted, remaining old plays stay pending for a
later attempt. Last.fm will show adjusted plays on the new date. The report lists
both original estimates and submitted dates, including when delivery succeeds.
Original dates stay in the pending queue until acknowledgement, and dates on the
iPod and submissions to ListenBrainz remain unchanged.

Last.fm's empty code-1 responses do not prove that artist metadata is wrong. The
report shows the captured queue metadata, which later Library edits do not
automatically rewrite. Pending listens are never silently dropped. See
[ADR-0102](adr/0102-adjust-old-lastfm-submission-dates.md) for the date policy.

The queue and capture cursors live in `scrobbles-v2.json` beside `settings-v2.json`.
They contain listening metadata and account names, not credentials. Preserve this
file across reinstalls to retain delivery history. If it is damaged, iOpenPod
preserves it and stops scrobbling rather than starting a fresh receipt history.
This Host's receipts do not deduplicate another computer's submissions. A response
lost after remote acceptance is inherently uncertain; exactly-once delivery is
not guaranteed. See [ADR-0101](adr/0101-retain-account-scoped-scrobble-delivery-on-the-host.md).

## Scrobble Ratings

**Settings → Sync → Sync behavior → Scrobble Ratings** is off by default. This one
setting applies to all connected Last.fm and ListenBrainz accounts during
**Scrobble now** and the enabled **Scrobble during Sync** step. It is independent
of **Sync star ratings to Host files**; no Host media files or iPod files are changed
by feedback work. The setting can also be overridden for an individual iPod.

- **4-5 stars:** Love on both services.
- **1-2 stars:** Unlove on Last.fm; Hate (score -1) on ListenBrainz.
- **3 stars, unrated, or unknown native values:** leave remote feedback unchanged.

Enabling the option includes existing rated Music and Music Video Tracks with
persistent identity and artist/title. New plays or usable playback dates are not
required. It uses committed iPod ratings after Playback Sidecar reconciliation,
before Sync changes or removes Tracks. Unsaved Library edits are not submitted.

Last.fm uses artist and title with the existing authorized session. Unlove removes
the track's loved status, including a Love previously set outside iOpenPod; it does
not express dislike. No MusicBrainz lookup or media-tag reads are needed for Last.fm.

For ListenBrainz, one valid embedded MusicBrainz recording ID takes precedence. Supported native tags
include ID3's MusicBrainz UFID and MP4's MusicBrainz Track Id. Release-track IDs are
not recording IDs. Missing, malformed, or conflicting IDs fall back to authenticated
artist/title lookup. An unmatched recording is skipped for that observed rating
and metadata; a later changed observation can try again. Matching is supplied by
ListenBrainz and can be imperfect.

Feedback has separate pending deliveries and receipts for each service/account in
version 4 of `scrobbles-v2.json`; versions 1-3 migrate without losing play history
or ListenBrainz feedback receipts. A failed feedback request never replays
acknowledged listens or another service's accepted feedback. Failed lookup and submission
requests remain pending, including after Track removal or restart. Unchanged
ratings do not resend; changed rating ranges replace pending intent.
Neutral ratings cancel unsent feedback without clearing the service's assignment.
Turning the setting off pauses both capture and delivery; account disconnection
also preserves pending work. Reconnecting the same account resumes it.

Reports show feedback accepted, pending and unmatched counts separately from
listens. Local receipts do not reconcile later website edits or other computers.
See [ADR-0268](adr/0268-sync-opt-in-listenbrainz-recording-feedback.md) and
[ADR-0269](adr/0269-share-rating-scrobbling-with-lastfm-loved-status.md).

## API contracts

Core submission contracts were checked on 2026-10-01; recording feedback, lookup
and Last.fm loved status were checked on 2026-11-14.

- [Last.fm desktop authentication](https://www.last.fm/api/desktopauth): signed
  `auth.getToken`, browser approval, and `auth.getSession`. Parameters are sorted
  by name, UTF-8 encoded, and signed with MD5 plus the application shared secret.
  The `format` parameter is excluded from the signature.
- [Last.fm track.scrobble](https://www.last.fm/api/show/track.scrobble): HTTPS form
  POSTs with UTC Unix start times, at most 50 entries, and per-entry
  `ignoredMessage.code` acknowledgements. HTTP success alone is insufficient.
  Acknowledgements are matched by echoed playback timestamp and uncorrected
  artist/title, never by response-array position. Unmatched or ambiguous responses
  retain the pending queue rather than clearing the wrong listens.
- [Last.fm track.love](https://www.last.fm/api/show/track.love) and
  [track.unlove](https://www.last.fm/api/show/track.unlove): signed HTTPS form POSTs
  with `artist`, `track`, `api_key` and session key `sk`. Rating requests select XML
  to require the documented empty `<lfm status="ok">` acknowledgement. Missing,
  malformed or failed acknowledgements leave feedback pending. DTDs are rejected.
- [Last.fm support: importing listening history](https://support.last.fm/t/importing-listening-history-spotify-apple-music-and-itunes-wmp/1424/3):
  old scrobbles have a 14-day backdating limit. iOpenPod adjusts those Last.fm
  submission dates as described above. Requests are paced and API errors stop
  that service's remaining batches.
- [ListenBrainz core API](https://listenbrainz.readthedocs.io/en/latest/users/api/core.html):
  `GET /1/validate-token` and `POST /1/submit-listens` with
  `Authorization: Token …`, `listen_type=import`, Unix `listened_at`, and
  `track_metadata`. Requests use at most 100 listens, below the documented maximum
  of 1,000, and validate the 10,240-byte per-listen limit.
- [ListenBrainz rate limits](https://listenbrainz.readthedocs.io/en/latest/users/api/index.html):
  pause when the remaining allowance reaches zero using `X-RateLimit-Reset-In`;
  retain pending work on HTTP 429 or a pause longer than one minute.
- [ListenBrainz recording feedback](https://listenbrainz.readthedocs.io/en/latest/users/api/recordings.html):
  `POST /1/feedback/recording-feedback` sends one `recording_mbid` and `score`, using
  the connected account token. The client requires `status=ok` acknowledgement.
- [ListenBrainz metadata lookup](https://listenbrainz.readthedocs.io/en/latest/users/api/metadata.html):
  `GET /1/metadata/lookup/` with `artist_name` and `recording_name` now requires
  authentication. An empty object means no match; malformed IDs remain retryable.

HTTP responses are bounded, credential-bearing redirects are refused, and network
and keyring operations run outside the Qt GUI thread. Tests use deterministic HTTP
doubles and virtual devices; live-account and physical-device acceptance remain
manual checks.

## Last.fm signature security constraint

Rechecked on 2026-10-25: section 8 of the
[Last.fm authentication specification](https://www.last.fm/api/authspec) requires
MD5 for `api_sig`. Replacing it with SHA-256 or another algorithm would break
authentication and Scrobble submission. This use remains an authentication
operation; it must not be relabeled as non-security hashing with
`usedforsecurity=False` to silence a scanner.

[Code-scanning alert #1](https://github.com/TheRealSavi/iOpenPod/security/code-scanning/1)
(`py/weak-sensitive-data-hashing`) identifies this protocol constraint. Retaining
Last.fm support requires accepting its legacy signature algorithm. The exception
is limited to Last.fm request signing, and should be revisited if Last.fm provides
a stronger supported scheme.

Requests use the fixed HTTPS service endpoint with certificate verification, and
the HTTP transport refuses redirects. Credentials remain in the native OS keyring;
the shared secret contributes to the signature but is not sent as a request
parameter. These controls limit exposure without making MD5 a strong algorithm.
