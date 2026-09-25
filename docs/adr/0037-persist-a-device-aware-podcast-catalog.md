# ADR-0037: Persist a device-aware Podcast Catalog

- Status: Accepted
- Date: 2026-09-12
- Extends: ADR-0005, ADR-0011, ADR-0019, and ADR-0029

The Podcasts browser consumes one immutable Podcast Snapshot from an Application
Layer Podcast Controller. The snapshot combines explicit subscriptions, refreshed
feed metadata, durable Listening History, and membership projected from the current
Active iPod's Library Snapshot. The GUI does not parse feeds, interpret iTunesDB
fields, or access device paths. Feed and Storage adapters remain internal seams of
the Podcast module and are replaceable in tests.

iOpenPod 2.0 stores its state under `iPod_Control/iOpenPod/Podcasts/`, separately
from the Original iOpenPod's files. `subscriptions-v1.json` contains versioned
show-level subscription metadata only; Podcast Episodes are fetched or projected
for the current runtime and are never stored in that document.
`listening-history-v1.json` contains versioned, independent episode history.
Removing an episode from the iPod or unsubscribing from its feed does not delete its
Listening Record. Existing malformed or future-version documents fail closed and
are left byte-for-byte unchanged. Writes use an identity-bound Filesystem Session,
exact source fingerprints, atomic replacement, verification, and a device flush;
unconditional overwrite is unavailable.

Every load reconciles iTunesDB Podcast Tracks before presentation. A normalized RSS
URL identifies the Podcast Subscription when present; otherwise the Podcast title
and author provide a deterministic device-only fallback. A normalized enclosure URL
identifies an episode across RSS and iTunesDB, followed by the RSS GUID and then
bounded title/date/number evidence. This makes `on_device` and the Track identity a
fresh projection rather than persisted truth. Podcast Tracks absent from the
subscription document create a subscription automatically. Play count, played flag,
and last-played time update Listening History, while an explicit user
listened/unlistened override remains authoritative.

Feed refresh uses the maintained `feedparser` dependency because real Podcast RSS
and Atom feeds vary substantially and use Apple namespace extensions. iOpenPod owns
the HTTP operation: URLs are restricted to HTTP(S), requests have deadlines and byte
limits, redirects are revalidated, descriptions become plain text, and parsed data
is translated into typed immutable records. The optional discovery dialog searches
Apple's public podcast directory and also accepts a direct RSS URL. Opening a
Podcast Subscription immediately refreshes its feed. Network and device work run
outside the GUI thread, and results started for an earlier Active iPod are
discarded.

Podcast artwork follows the same source split as the catalog. An iTunesDB Artwork
ID is a fresh device projection and is never serialized into the subscription
document. Publisher-feed artwork URLs are cached metadata; their image bytes
are fetched lazily through a bounded Application Layer loader, decoded away from
the GUI thread, and retained only in byte-bounded memory caches. Presentation uses
current iPod artwork while remote artwork is unavailable and a deterministic local
placeholder only when neither source can produce a cover.

## Amendment: publisher-feed artwork only (2026-09-25)

The original decision also retained Apple directory artwork as a subscription
fallback. Apple's [Search API terms](https://performance-partners.apple.com/search-api)
restrict promotional image assets and attach store-promotion requirements.
The directory adapter now retains only textual discovery metadata and the feed
URL. Search results have no artwork field or image-loading dependency, and
subscription fetches use only the publisher's feed for remote artwork. The
directory UI uses complete text rows rather than empty image placeholders.

Already saved subscriptions do not record whether an artwork URL came from a feed
or from the earlier directory fallback. Do not delete these user-controlled values
based on a hostname guess. The existing feed-refresh workflow replaces their
metadata with the current publisher-feed values, including an empty artwork URL
when the feed supplies none. Device artwork and publisher-feed images remain
available under the existing source and cache boundaries.

This decision implements Podcast discovery, subscription, refresh, browsing,
listened/unlistened state, current-device status, and playback of on-device Tracks.
It does not authorize direct Podcast media download, automatic retention, or
add/remove publication. Those operations must join the Library Draft, review, and
Storage Transaction workflow when general Sync and non-music import are designed;
the browser must not create a second device-media writer.
