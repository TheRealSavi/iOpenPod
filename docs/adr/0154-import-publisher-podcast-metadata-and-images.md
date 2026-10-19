# ADR-0154: Import publisher Podcast metadata and images

- Status: Accepted
- Date: 2026-10-19
- Extends: ADR-0037, ADR-0091, ADR-0138, and ADR-0149

## Scope and source policy

The user selected richer show and Episode metadata, publisher Episode covers, and
chapter artwork from the [source investigation](../research/apple-podcasts-capabilities-2026-10-19.md).
External chapter navigation, description chapter detection, transcripts, Apple
Lookup, alternate enclosures, and other service features remain outside this change.

Incoming Podcast covers prefer a usable embedded Episode cover, then the item's
publisher RSS image, then the publisher show cover. Missing covers on retained
Episodes can use the same Episode/show fallback without a media download. Existing
artwork is not replaced merely because a feed image changes. Apple directory
promotional images remain excluded.

Publisher chapter-image sources include inline Podlove images and JSON resources
linked through `podcast:chapters`. Only image URLs and Artwork Display Times enter
the new source model. Titles, chapter links, and navigation are not imported.
Silent JSON markers can supply pictures. Embedded ID3 pictures win at an identical
time; inline publisher images precede JSON images at ties. A failed image does not
claim that time, so another usable image at the same time can supply it.
Previously imported media chapters remain unchanged.

The shared Sync artwork batch bounds downloads, image dimensions and retained
pixels, reuses repeated URLs, supports cancellation, and treats unavailable optional
images/documents as warnings. Chapter images preserve aspect ratio before native
thumbnail preparation. Image times must be ordinary finite nonnegative positions
within the prepared media. The normal timed-artwork writer supplies time zero,
target representations, counts, verification, and transactional publication.
This source import does not establish firmware playback acceptance.

## Metadata and persistence

Podcast Subscriptions retain ordered distinct category names, copyright, website,
and serial/episodic show type. The original primary category remains available for
native metadata. Category parents and children retain their source order as names;
this does not introduce a new category-tree model. Show type does not override
saved retention settings or native traversal policy.

Episodes retain an individual publisher author, full/bonus/trailer type, website,
and HTTP(S) links extracted from show notes. Native artist uses the Episode author
when supplied, while album artist remains the show's author. Show copyright maps
to the existing native copyright field. Episode types and websites have no invented
native field mapping; the Podcast browser presents them. RSS email-only author
fields are not used as artist names. Browser links require a user action.

Subscriptions now encode version 3 at the existing `subscriptions-v1.json` path,
with backward reads of versions 1 and 2. Version-2 retention choices survive the
upgrade; older applications reject version 3 instead of silently discarding new
metadata. Listening History remains version 2. Episode catalogs, Episode artwork
source URLs, and chapter-image sources remain runtime projections, not another persisted
Episode database. Reopening a show refreshes its publisher metadata; native artist
and copyright remain available independently of that refresh.

## Validation

Synthetic feeds cover namespace prefixes, field precedence, unavailable optional
metadata, links, persistence, and reconciliation. Artwork tests cover bounded JSON,
silent markers, duplicate times, embedded precedence, corrupt sources, aspect ratio,
memory limits, and cancellation. Production Sync tests reparse Classic and Nano
output after forced transcoding and verify each image/time, unchanged chapter
navigation, and the mapped author/copyright fields. Physical firmware behavior
remains a separate acceptance check.
