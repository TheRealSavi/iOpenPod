# ADR-0266: Keep Podcast logins on the Host and scope HTTP authentication

- Status: Accepted
- Date: 2026-11-13
- Extends: ADR-0037, ADR-0091, and ADR-0101

Private Podcast Subscriptions can use a username and password through HTTP Basic
authentication over HTTPS. Add Podcast accepts separate login fields and extracts
percent-encoded URL userinfo at the input boundary. The canonical feed URL remains
credential-free; password changes do not change the Subscription identity. Internal
URL validation continues to reject userinfo. Publisher resource URLs containing
userinfo are not imported as downloadable media or artwork.

Credentials belong to the Host and the canonical feed URL. They never become
Subscription fields, Listening History, Sync intent, or native iPod metadata.
The existing keyring dependency supplies a shared native-vault adapter for
Podcasts and scrobbling. Plaintext and null backends remain unavailable. A hashed
feed URL identifies the vault entry; its username and password are stored together
as the secret. A new Host must obtain its own login.

Remember on this computer saves a verified login in that vault. Session-only
entry works without a vault and overrides a previously remembered login until
application shutdown; it does not delete the remembered entry. Forget Login removes
both the temporary and saved login explicitly. Unsubscribing on an iPod does not
erase a Host login that another iPod may use. Vault failures are reported and never
fall back to a plaintext file. Public requests do not consult the vault.

The feed is fetched and parsed before a supplied login is saved. Credentials are
saved before publishing Subscription changes, so a vault-save failure does not
publish an unusable new Subscription. The OS vault and device publication do not
share a transaction: a validated login may remain on the Host if subsequent device
publication fails or the iPod disconnects. Retrying reuses that login.

All Podcast HTTP requests use the same transport policy, including streamed
Enclosure downloads, publisher covers and Chapter image documents. A caller names
the owning feed explicitly. Credentials are eligible only for its exact HTTPS
scheme, hostname and effective port, including after redirects. A public CDN may
receive an unauthenticated request, but cannot obtain the feed login by issuing a
challenge. No origin-wide credential registry, global opener, browser cookies or
implicit cross-host trust is introduced. HTTPS-to-HTTP redirects and redirect URLs
with userinfo are rejected before following them. This strengthens the earlier
feed client's final-URL-only validation into validation of every redirect.

Explicitly entered credentials can be sent on the initial authorized request;
saved credentials are retrieved after a Basic challenge and retried once. Missing,
rejected, forbidden and unsupported authentication have distinct typed failures.
Server reason text, response bodies and raw network exceptions do not enter user
diagnostics. Feed failure continues to exclude that Subscription from automatic
retention changes; failed replacements retain their existing Tracks.

Login controls remain open for correction on failure and clear entered secrets on
close. Changing a login invalidates remote artwork results so an earlier failure or
account's cached image cannot decide the next request. Artwork request caches carry
feed context. Network and vault work remain outside the GUI thread.

Tests exercise urllib's real redirect/error handlers with an in-memory HTTPS peer,
including feed and media authentication, different origins and ports, downgrade
rejection, retry limits, credential redaction, vault failures and dialog retries.
Crrow777's paid-feed instructions require membership; compatibility with an actual
paid account remains an external acceptance check. This decision supports standard
HTTP Basic feeds, not website form-login or bearer-token extraction.
