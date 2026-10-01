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

## API contracts checked on 2026-10-01

- [Last.fm desktop authentication](https://www.last.fm/api/desktopauth): signed
  `auth.getToken`, browser approval, and `auth.getSession`. Parameters are sorted
  by name, UTF-8 encoded, and signed with MD5 plus the application shared secret.
  `format=json` is excluded from the signature.
- [Last.fm track.scrobble](https://www.last.fm/api/show/track.scrobble): HTTPS form
  POSTs with UTC Unix start times, at most 50 entries, and per-entry
  `ignoredMessage.code` acknowledgements. HTTP success alone is insufficient.
  Acknowledgements are matched by echoed playback timestamp and uncorrected
  artist/title, never by response-array position. Unmatched or ambiguous responses
  retain the pending queue rather than clearing the wrong listens.
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

HTTP responses are bounded, credential-bearing redirects are refused, and network
and keyring operations run outside the Qt GUI thread. Tests use deterministic HTTP
doubles and virtual devices; live-account and physical-device acceptance remain
manual checks.
