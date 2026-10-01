# ADR-0101: Retain account-scoped scrobble delivery on the Host

- Status: Accepted
- Date: 2026-10-01
- Extends: ADR-0014, ADR-0015, ADR-0076, ADR-0100
- Amended by: ADR-0102 for Last.fm submission dates outside its backdating window

## Decision

Scrobbling submits committed iPod music playback evidence to Last.fm and
ListenBrainz. The Maintenance action and optional Sync step share one Application
Layer workflow. Sync captures and attempts delivery before media preparation and
removals, including removal-only and otherwise unchanged Syncs. The setting defaults
on, but nothing is submitted until the user connects an account. Disabling the Sync
step does not disable the manual action.

The firmware's aggregate Unscrobbled Plays count cannot distinguish two service
accounts or partial batch acceptance. It remains unchanged as playback evidence.
Instead, an account-scoped **Scrobble Queue** on the Host retains captured listens
and observed cumulative-play cursors. Only positively acknowledged entries leave
the queue. A failed second service never causes replay to the first. Already
captured entries survive Track removal, account disconnection, and application
restart; reconnecting the same account resumes them.

Storage atomically replaces `scrobbles-v2.json` in the application configuration
directory. A Host Resource Lease serializes participating processes across capture,
network submission, and receipt persistence. Unreadable state is preserved and
blocks submission, rather than silently discarding duplicate-prevention history.
Failure to capture/persist the queue stops Sync before device mutation; service
failures become warnings while Sync can continue. The queue is bounded to 50,000
pending account deliveries. Receipts belong to a Volume Identity, persistent iPod
Track ID, service, and case-insensitive account name, never a Mount Point or
Connection Generation.

Last.fm uses signed desktop browser authorization. Users supply their application's
API key and shared secret; iOpenPod has no bundled application credentials.
ListenBrainz validates a user token. The `keyring` dependency stores credentials
only in native Windows Credential Manager, macOS Keychain, Secret Service, or
KWallet backends. Plaintext and null backends are rejected. This adds native vault
integration and its platform dependencies in exchange for keeping secrets out of
settings, queue files, device files, and logs. Account names and the Sync option are
ordinary global settings. Passwords are never requested.

## Evidence and limits

The Original iOpenPod's scrobble planner and Last.fm/ListenBrainz clients establish
the pending-count and backwards-duration timestamp baseline. This implementation
uses independent typed clients and retains per-entry acknowledgements, rather than
treating a batch's HTTP success or total accepted count as proof for every listen.

iPods retain an aggregate count and last-played time, not every playback start.
Starts are estimated backwards from last-played by Track duration. Missing,
ambiguous, future, or out-of-range dates are skipped. ADR-0102 allows adjusting
usable Last.fm dates outside its backdating window, retaining the original
estimate separately. Only Music and Music Video Tracks longer than 30 seconds with artist,
title, duration, and persistent identity qualify. Podcast Listening History and
runtime Playback History are separate concepts and are not submitted.

Ordinals use cumulative play counts, so unchanged evidence does not replay when
the pending counter remains nonzero. A restored/decreased cumulative count is
treated conservatively: previously observed ordinals are not replayed. This can
omit plays after an external counter reset until the old high-water mark is
exceeded. Receipts are local to this Host; switching Hosts or deleting receipt
state can replay history. This does not claim cross-Host deduplication.

Neither service offers a transaction shared with Host persistence. A lost response
or failure to save an accepted receipt can require retrying an uncertain delivery;
exactly-once delivery cannot be guaranteed. Cancellation and disconnection stop
before further batches, but an acknowledgement already received is persisted
first. Rejected Last.fm entries remain pending, with the service's reason shown.
See [Scrobbling](../scrobbling.md) for current API references and operating details.
