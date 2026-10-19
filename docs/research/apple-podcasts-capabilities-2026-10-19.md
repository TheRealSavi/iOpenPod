# Apple Podcasts data available to iOpenPod

Research date: **2026-10-19**. This is a capability and implementation-gap
investigation, not an accepted architecture decision or a product implementation.
Repository observations include the existing working-tree changes on top of
`30ab5aab6bd57c91dad3995aef43c946898ef9b7`. Original iOpenPod was inspected at
`origin/1.x`, commit `a20242428b93b672d14b37230772dbad75139c69`.

Follow-up: [ADR-0154](../adr/0154-import-publisher-podcast-metadata-and-images.md)
records the selected implementation: richer show and Episode metadata, publisher
Episode covers, and chapter images. The inventory below describes the research
baseline; its other suggested features remain outside the selected scope.

## Main finding

The largest useful additions are **publisher RSS episode artwork, external chapter
lists, external chapter pictures, and chapters in episode descriptions**. The native
output machinery already exists: Track metadata, chapter data, and timed ArtworkDB
images. Most missing work belongs in source acquisition and normalization.

There are three different inputs:

1. **Apple's public iTunes Search/Lookup API** discovers shows and episodes.
2. **Publisher RSS/Atom feeds and their linked resources** supply downloadable media
   and richer metadata, including episode art, chapters, and transcripts.
3. **The downloaded media** can contain embedded metadata, covers, and chapters.

Features visible in the modern Apple Podcasts app do not automatically become
public API data or legacy iPod features. In particular, Apple-generated chapters
and transcripts are not documented Search/Lookup exports. See
[Apple's chapter documentation][apple-chapters] and the service limits below.

## What this checkout actually uses

| Path | Current behavior |
| --- | --- |
| [Directory/feed adapter][feed-client] | Calls `https://itunes.apple.com/search` with `media=podcast`, `entity=podcast`, default country US, default 25 results, application cap 50. Retains only show title, publisher, feed URL, primary category, and episode count. |
| [Podcast models][models] | Show metadata includes description, artwork URL, category, and language. Episode metadata includes GUID, title, description, subtitle, enclosure URL, date, duration, size, episode/season numbers, and advisory. Episodes have no artwork URL, chapter-source, transcript, episode-type, or individual-author field. |
| [Feed normalization][feed-client] | Reads show artwork, the first category, and one playable enclosure per Episode. Converts descriptions to plain text and collapses whitespace. Does not consume external chapters or episode images. |
| [Episode-to-Track mapping][media] | Supplies title, show/album, show author as artist/album artist, publication year/date, episode/season numbers, GUID/feed identity, descriptions, category, advisory, and Podcast playback policy. |
| [Sync executor][sync] | Incoming covers prefer usable embedded episode images, then publisher show covers. Retained missing covers have feed-based and captured-media repair paths. New ID3 chapter pictures enter timed Artwork Assets. |
| [Chapter conversion][chapters] | Sorts media-inspected chapters and converts their titles and start positions to `TrackChapter`. |
| [Embedded picture capture][embedded] | Reads original downloaded media before transcoding can discard covers. Chapter images specifically use ID3 `CHAP` subframe `APIC`, restricted to imported chapter times. This is not a general MP4 chapter-image extractor. |

There is no current Lookup client. Original iOpenPod's
[directory implementation][original-search] had show lookup by collection ID,
and its [feed adapter][original-feed] also omitted the richer per-episode sources.
Restoring shared Apple link resolution would therefore recover baseline behavior;
RSS chapter/artwork enrichment extends it.

[ADR-0037][adr-catalog] deliberately excludes Apple directory promotional artwork.
The recommended additions below use publisher feeds or embedded media. Apple's
[API terms][apple-api] distinguish promotional assets from ordinary discovery data;
this research does not propose changing the accepted source policy.

## Public Apple API inventory

Apple documents show, author, and episode searches, ID lookup, storefront selection,
search attributes, explicit-content filtering, and result limits up to 200. Its
published guidance describes an approximate 20-request-per-minute limit, subject
to change. Cache and debounce discovery requests. These capabilities are broader
than this checkout's show-only search. [Apple API documentation][apple-api].

The following is an **observed field inventory**, not a promise that every result
always has every field. On the research date, both sampled shows returned these
groups from Search and `lookup?entity=podcastEpisode&limit=3`.

| Data group | Observed fields | Useful application |
| --- | --- | --- |
| Identity/classification | `wrapperType`, `kind`, `collectionId`, `trackId`; episode `artistIds` | Resolve shared Apple links, distinguish show/episode rows, retain directory provenance. Keep Apple numeric IDs separate from the Podcast GUID and native Track identity. |
| Names and attribution | `collectionName`, `trackName`, show `artistName`; show `collectionCensoredName`, `trackCensoredName` | Search and preview. Publisher feed names remain the existing import source. |
| Locations | `feedUrl`, `collectionViewUrl`, `trackViewUrl`; episode `episodeUrl`, `previewUrl` | Feed discovery, open-in-browser links, possible episode matching. Do not treat a preview as an authoritative complete enclosure. |
| Episode text | `description`, `shortDescription` | Episode discovery preview and possible explicitly defined fallback. No need to replace working publisher descriptions. |
| Timing/counts | `releaseDate`, `trackTimeMillis`; show `trackCount` | Discovery hints. A show's count is not an episode catalog; inspect downloaded media for final duration. |
| Genre/advisory | `genres`, `contentAdvisoryRating`; show `genreIds`, `primaryGenreName`, `collectionExplicitness`, `trackExplicitness` | Better discovery filters and metadata fallback, with source-specific advisory normalization. |
| Images | Show `artworkUrl30`, `artworkUrl60`, `artworkUrl100`, `artworkUrl600`; episode `artworkUrl60`, `artworkUrl160`, `artworkUrl600` | Available URLs, intentionally excluded from import by ADR-0037. An episode result's image need not be unique episode art. |
| Media hints | Episode `episodeContentType`, `episodeFileExtension`, `closedCaptioning` | Preview/filter hints, not proof of codec compatibility or a downloadable caption file. |
| Publisher episode identity | `episodeGuid` | Correlate with the publisher's GUID within the correct show. Never replace the GUID with Apple's numeric `trackId`. |
| Store metadata | `country`; show `currency`, `collectionPrice`, `trackPrice`, `collectionHdPrice` | Store presentation only; not an iPod purchase, entitlement, or account record. |

No chapter list, chapter-image timeline, or transcript resource appeared in those
episode results. The reviewed public Search/Lookup documentation supplies no
contract for retrieving them. Use the feed and media sources below. A bounded
Lookup result is not evidence of a complete archive or a supported pagination
scheme.

## Publisher metadata: current coverage and useful additions

These RSS fields are described in Apple's [RSS guide][apple-rss] and
[feed requirements][apple-feed]. The current-coverage column comes from the local
adapter and models, not from Apple's feature claims.

| Source metadata | Current coverage | Possible iPod or application use |
| --- | --- | --- |
| Show title, author, description | Read | Already supplies show identity/presentation, album, artist, and album artist. |
| Show image: `itunes:image`, RSS image | Read | Already supplies the publisher cover fallback. Native Episode artwork and the application's show cover are distinct relationships. |
| Language and category hierarchy | Language and first category read | Language is retained at show level; preserve multiple categories for Host browsing. A mapping to native locale fields needs an explicit policy. |
| Copyright and website | Not projected from feed | Copyright has an existing `TrackMetadata.copyright` destination; show/episode website links are useful on the Host. |
| `itunes:type`: serial/episodic | Not modeled | Suggest browsing/order defaults. Do not override saved Newest/Next Sync settings or captured native ordering automatically. |
| Episode title, GUID, enclosure, publication, duration | Read | Existing Track identity, metadata, and media preparation. File inspection remains authoritative for actual media facts. |
| Description/subtitle | Read as flattened text | Existing native description and subtitle. Preserve a structured source long enough to extract chapter timestamps and links. |
| Episode author, `itunes:title`, richer `content:encoded` | Not explicitly selected | Better per-episode artist/title/text when a documented precedence policy supports them. Avoid unconditionally overwriting useful embedded or reviewed metadata. |
| Episode and season numbers | Read | Already mapped to native metadata; seasons do not create separate native show albums. |
| Explicit/clean declarations | Read, including show fallback | Already mapped to `ContentAdvisory`; episode declarations take precedence. |
| `itunes:episodeType`: full/bonus/trailer | Not modeled | Host badges and optional selection controls; no demonstrated native Podcast episode-type field in the semantic contract. |
| Episode `itunes:image` | Dropped | Highest-value cover addition: feed-specific Episode cover before the show fallback. [Episode artwork][apple-episode-art]. |
| Feed relocation/completion/blocking metadata | Not acted upon as lifecycle policy | Migration or status hints. `itunes:block` concerns Apple directory visibility, not authority to delete a user's local Episodes. Moving a feed requires preserving Subscription and Listening History identity. |

Artwork uploaded only in Apple Podcasts Connect is not thereby available through a
publisher feed. Similarly, lower-resolution directory image URLs should not be
rewritten speculatively to manufacture an original publisher asset.

The newer [`podcast:image`][namespace-image] supports multiple purposes, sizes,
aspect ratios, types, and alternative text, including non-static assets. Select an
appropriate static artwork source deliberately. The older
[`podcast:images`][namespace-images] supplies `srcset` and is deprecated; support
it for compatibility rather than making it the only new image extension. Neither
is currently modeled. Apple's hero/channel/subscription artwork placements are
not a guarantee of public feed resources. [Apple artwork guide][apple-artwork].

## Chapters and pictures

Apple accepts publisher chapters from episode descriptions, `podcast:chapters`,
and embedded MP4/ID3 metadata. Description chapters start at zero and contain at
least three entries under Apple's publishing guidance. That guidance is not a
reason to reject valid shorter chapter lists from other formats or retained iPod
data. [Apple chapters][apple-chapters].

| Source | Current import | Implementation opportunity |
| --- | --- | --- |
| Embedded media chapter names/times | Supported when Media Inspection exposes them | Retain this path and its actual-duration validation. |
| ID3 `CHAP` + nested `APIC` pictures | Supported | Already produces separate timed ArtworkDB images, including after transcoding. Linked APIC pictures are not fetched. |
| RSS `podcast:chapters` JSON | Missing | Fetch the linked bounded document; map valid `startTime` and title to native chapters. Fetch optional `img` independently for timed artwork. Preserve link/TOC metadata on the Host if useful. |
| Podlove Simple Chapters in RSS | Missing | Parse inline `psc:chapters`/`psc:chapter` times, titles, optional images and links. No chapter-list download is needed for inline data; the format also supports external resources. |
| Timestamps in episode description | Missing | Parse line/paragraph structure before `_plain_text` collapses it. Use a conservative recognizable chapter block, not every timestamp anywhere in prose. |
| MP4 chapter images | No general extractor identified | Separate format investigation with actual samples; do not claim the ID3 image reader handles them. |
| Apple-generated chapters | No public retrieval contract found | Can be used if a publisher exports and republishes them in the public description/feed; Connect export is a creator workflow. |

[`podcast:chapters`][namespace-chapters] supplies the resource URL/type; the preferred
JSON MIME type is `application/json+chapters`. In the [JSON format][json-chapters],
`startTime` is required while `title`, `img`, `url`, `endTime`, and `toc` are optional.
In particular, `toc=false` is a silent marker: retain its timed image without
inventing a navigable chapter. Optional end times, URLs, and geographic fields have
no equivalent in the current `TrackChapter` contract. Chapter documents can change
independently of the audio.

[Podlove][podlove] identifies its XML elements by namespace URI and allows fractional
timestamps. Parse by namespace rather than a fixed prefix. [ID3][id3-chapters]
additionally permits hierarchy/order through `CTOC`, overlapping chapters, and
chapters outside the table of contents. The present chronological projection does
not model all of those semantics. That is another reason to preserve source
meaning before projecting the simpler native list.

The native mapping is already narrow and useful:

- `TrackChapter(title, start_ms)` becomes iTunesDB MHOD 17 chapter data. Later
  devices also receive chapter blobs through the SQLite Library Artifact Set.
- Chapter image bytes become `TimedArtworkFrame(display_time_ms, pixels)` inside
  a `TimedArtworkAsset`; they are not embedded in MHOD 17.
- Artwork preparation creates the Device Profile's required representations.
  [ADR-0138][adr-timeline] and [ADR-0139][adr-chapter-formats] own timing and count
  policy. URLs, interactive links, and transcript cues are not native chapter fields.

Do not equate a chapter list with an image timeline. A chapter can have no picture;
an image can be useful without a navigable chapter. Optional image failure should
leave the valid chapter list and media usable. A fallback image at time zero must
be explicit, and missing later images must not invent unavailable publisher art.

The remote cover loader currently center-crops to square. Reusing it unchanged for
chapter slides could crop meaningful content. Chapter-image import should use
bounded decoding with a documented fit/padding policy for the actual target
representation, consistent with the existing native artwork preparation.

## Transcripts, links, and other publisher extensions

Apple can generate transcripts, ingest publisher transcripts, and let creators
export them through Connect. That is not a documented public listener transcript
API. Public [`podcast:transcript`][namespace-transcript] resources can supply text,
HTML, VTT, SRT, or JSON, potentially in multiple languages. This checkout does not
consume them. Host reading/search is a natural addition. Exporting plain text as
lyrics or iPod Notes would be a separate feature with size, formatting, and device
compatibility decisions; synchronized transcript highlighting is not established
by the existing chapter writer. The repository's [lyrics investigation][lyrics]
documents the embedded-tag path, not native Podcast transcript support.
[Apple transcripts][apple-transcripts].

Publisher chapter links and timestamped description links can be retained for Host
browsing. Apple's automatically identified links are a separate service feature
without a documented Search/Lookup export. Offline legacy firmware does not gain
modern web interactions from storing chapter titles. [Apple links][apple-links].

The wider namespace offers the following additional inputs. These are **publisher
extensions**, not additional Apple API permissions, and they are not currently
modeled by this Podcast adapter. Suggested uses are opportunities, not a proposal
to implement all of them.

| Extension | Available data | Useful disposition |
| --- | --- | --- |
| [Season](https://podcasting2.org/docs/podcast-namespace/tags/season) | Season number and name | Preserve names on Host; map compatible numbers deliberately. |
| [Episode](https://podcasting2.org/docs/podcast-namespace/tags/episode) | Decimal number and display label | Host display; do not silently truncate into the native integer field. |
| [Alternate enclosure](https://podcasting2.org/docs/podcast-namespace/tags/alternate-enclosure) | Alternate codec, bitrate, language, audio/video sources and integrity metadata | Valuable future selection of a compatible downloadable version; inspect actual bytes. |
| [Person](https://podcasting2.org/docs/podcast-namespace/tags/person) | Credits, roles, portraits, links | Host credits; avoid treating every guest as the Track artist. |
| [Location](https://podcasting2.org/docs/podcast-namespace/tags/location) | Place/geographic metadata | Host details. |
| [License](https://podcasting2.org/docs/podcast-namespace/tags/license) | License identifier or URL | Host provenance. |
| [GUID](https://podcasting2.org/docs/podcast-namespace/tags/guid) | Stable show UUID | Feed migration/correlation; distinct from the Podcast Episode GUID. |
| [Medium](https://podcasting2.org/docs/podcast-namespace/tags/medium) | Podcast/video/music/audiobook/course and other feed kinds | Avoid assuming every feed is an ordinary audio Podcast. |
| [Trailer](https://podcasting2.org/docs/podcast-namespace/tags/trailer) | Show/season trailer media | Optional discovery; separate from an item's episode type. |
| [Soundbite](https://podcasting2.org/docs/podcast-namespace/tags/soundbite) | Highlight interval | Host preview, not a new Episode identity. |
| [Podroll](https://podcasting2.org/docs/podcast-namespace/tags/podroll) | Creator recommendations | Host discovery. |
| [Publisher](https://podcasting2.org/docs/podcast-namespace/tags/publisher) | Publisher feed relationship | Host organization. |
| [Content link](https://podcasting2.org/docs/podcast-namespace/tags/content-link) | Alternative external destination | Host browser link. |
| [Social interaction](https://podcasting2.org/docs/podcast-namespace/tags/social-interact) | Official discussion destinations | Separate Host feature. |
| [Chat](https://podcasting2.org/docs/podcast-namespace/tags/chat) | Chat server/room details | Separate Host network feature. |
| [Funding](https://podcasting2.org/docs/podcast-namespace/tags/funding) | Support links | Optional Host links. |
| [Value](https://podcasting2.org/docs/podcast-namespace/tags/value) | Payment protocols/recipients | Separate payment feature; no native iPod mapping. |
| [Live item](https://podcasting2.org/docs/podcast-namespace/tags/live-item) | Event state/schedule and stream sources | Separate streaming feature; not automatically an offline media file. |
| [Update frequency](https://podcasting2.org/docs/podcast-namespace/tags/update-frequency) | Release schedule/completion | Host refresh hints. |
| [Podping](https://podcasting2.org/docs/podcast-namespace/tags/podping) | Feed update notification support | Optional refresh integration. |
| [Locked](https://podcasting2.org/docs/podcast-namespace/tags/locked) | Hosting import preference | Hosting migration semantics, not DRM. |
| [Block](https://podcasting2.org/docs/podcast-namespace/tags/block) | Platform ingestion/display preference | Discovery policy, not deletion authority. |
| [TXT](https://podcasting2.org/docs/podcast-namespace/tags/txt) | Purpose-specific verification/text signals | Support only deliberately understood purposes. |

## Apple service and media availability limits

- Public Lookup does not promise personal follows, listening progress, ratings,
  recommendations, subscriber entitlements, or creator analytics. Their absence
  from the documented contract is not a claim that private Apple endpoints cannot
  exist. iOpenPod's Listening History remains its separate device-aware state.
- Some shows have no public RSS feed or withhold its availability to other apps.
  Treat an unavailable `feedUrl` as a valid outcome. [Apple show submission][apple-submit].
- Paid Apple benefits can include audio absent from public RSS. Search results are
  neither a subscriber download route nor an entitlement. User-supplied private
  publisher feeds are a separate source; current URL normalization rejects
  user/password components and there is no Apple subscriber login integration.
  [Apple subscription delivery][apple-subscriptions].
- Ordinary public video enclosures can pass through the existing media inspection
  and transcoding workflow if the target Device Profile permits the result.
  [Apple RSS video][apple-video] does not establish legacy codec compatibility.
- Apple's newer HLS publishing integration uses creator/hosting-provider API keys.
  It does not supply this app with a public Search API download contract, and HLS
  manifests are not ready-to-copy iPod media. [Apple HLS publishing][apple-hls].
- Apple-generated chapters are documented for supported modern app versions and
  eligible content, with creator TXT export through Connect. Availability in that
  app alone cannot be offered as an iOpenPod feature. [Apple chapters][apple-chapters].

## Device limits

The supported product target is filesystem-accessible full-size iPods, Classic,
Mini, and Nano, as recorded in [ADR-0004][adr-original]. It excludes iPod touch
and shuffle. The [existing primary-source investigation][native-research] cites
Apple manuals describing chapter navigation and, on color models, changing Podcast
artwork. Mini artwork is an application display feature, not a promise of native
color artwork.

Successful database writing does not establish successful playback on every model.
The project's physical Classic readback previously found correctly stored timed
images that did not change during playback; the later format/count policy still
requires firmware acceptance testing. Keep those limits visible when adding new
sources. Native show browsing also uses representative Track/album relationships;
this report does not establish an independent native show-cover slot that can
always differ from every Episode cover.

## Recommended implementation increments

These are proposals for separate reviewable changes, not new accepted decisions.

1. **Episode artwork from publisher feeds.** Add a typed Episode artwork source,
   preserve it through catalog projection, and make remote preparation work per
   Episode rather than only per Subscription. Preserve current embedded-first
   behavior initially: embedded Episode cover, feed Episode cover, show cover.
   Keep user-edited existing artwork and later timeline groups intact. If RSS is
   later preferred over embedded art, record that deliberate policy change.
2. **External chapter lists and chapter images.** Add typed chapter-source and
   resolved-chapter records. Fetch JSON only for selected Episodes, import Podlove
   inline lists, and reuse the existing chapter/timed-artwork outputs. A useful
   initial precedence is valid embedded list, structured publisher list, then
   recognized description chapters. Treat that precedence as a proposal and select
   one coherent list; do not concatenate competing timelines or pair pictures by
   array index. Preserve explicit Library Draft edits.
3. **Description chapters and richer metadata.** Retain source line breaks before
   display cleanup; add episode author/type, copyright, links, and show type with
   explicit field precedence. Keep user retention settings separate from publisher
   hints. This can be split from the artwork work.
4. **Apple shared-link resolution.** Add bounded Lookup using the Apple ID and
   storefront, then obtain the publisher feed. Episode links can select a matching
   GUID within that feed. Handle missing feeds and unavailable/paid results without
   fabricating an enclosure. This is discovery work, not a prerequisite for RSS
   artwork or chapters.
5. **Publisher transcripts and alternate enclosures.** Consider these after the
   direct native chapter/artwork improvements: transcripts primarily enhance Host
   reading, while alternate downloads may reduce unnecessary transcoding. Keep
   live/social/payment features and creator-service integrations separate.

New source acquisition belongs in `iOpenPod/app/podcasts`; iPodDB receives typed
metadata and owned pixels. Device Registry supplies target capabilities, and
Storage retains sole ownership of device mutation. Reuse the shared Sync review,
verification, and Storage Transaction rather than creating a Podcast-only writer.

External resources need bounded byte/image/entry counts, HTTP(S) validation,
cancellation, and per-resource error handling. Capture the chosen resources for
one preparation; validate chapter times against the prepared media. Dynamic ad
insertion or publisher revisions can make an otherwise valid timeline wrong for a
particular download. Duration checks alone cannot prove perfect alignment.
Enrichment failure should preserve existing good data and allow valid media to Sync
without the optional enhancement.

## Verification performed

- Read the current source, relevant ADRs, native chapter/artwork contracts, and the
  Original iOpenPod adapters. Existing user-owned changes were included in the
  assessment and left intact.
- Fetched public Search, episode Lookup, and publisher RSS for Accidental Tech
  Podcast and Podcasting 2.0. Each Lookup returned one show and three Episodes.
  The latter feed exposed episode images, chapter links, and transcript links.
- Probed the installed `feedparser` **6.0.14** with a synthetic feed. It exposed
  `image`, `itunes_episodetype`, `podcast_chapters`, `podcast_transcript`, and
  `psc_chapters`; this app's typed Episode projection discarded them. Description
  `00:00 Intro\n02:00 Topic` became `00:00 Intro 02:00 Topic`.
- The sampled first Podcasting 2.0 chapter URL returned HTTP 400. The feed's presence
  of a chapter link is therefore not evidence that its document/images can currently
  be retrieved. No media or artwork was downloaded for this investigation.
- Ran existing feed, Podcast chapter, embedded artwork, and retained cover tests:
  **29 passed**. This verifies the covered software paths, not physical firmware.

The read-only probe and response captures remain ignored under `.scratch/`.
Future implementation should add synthetic fixtures for item-vs-show artwork,
chapter-source precedence, namespace prefix variants, broken external resources,
invalid/out-of-range times, duplicate image times, transcoding, and cancellation.
Verify resulting MHOD 17, SQLite chapter blobs, ArtworkDB time groups and saved
image counts, then test playback/forward/reverse seeking on representative physical
models. No product behavior was changed by this research.

## Sources

[feed-client]: ../../src/iOpenPod/app/podcasts/feed_client.py
[models]: ../../src/iOpenPod/app/podcasts/models.py
[media]: ../../src/iOpenPod/app/podcasts/media.py
[sync]: ../../src/iOpenPod/app/sync_execution.py
[chapters]: ../../src/iOpenPod/app/media/chapters.py
[embedded]: ../../src/iOpenPod/app/media/sync_artwork.py
[adr-catalog]: ../adr/0037-persist-a-device-aware-podcast-catalog.md
[adr-original]: ../adr/0004-use-original-iopenpod-as-the-compatibility-baseline.md
[adr-timeline]: ../adr/0138-edit-artwork-by-display-time.md
[adr-chapter-formats]: ../adr/0139-complete-timed-artwork-formats-and-counts.md
[native-research]: podcast-primary-sources.md
[original-search]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/podcasts/itunes_search.py
[original-feed]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/podcasts/feed_parser.py
[apple-api]: https://performance-partners.apple.com/search-api
[apple-rss]: https://help.apple.com/itc/podcasts_connect/en.lproj/itcb54353390.html
[apple-feed]: https://podcasters.apple.com/support/823-podcast-requirements
[apple-episode-art]: https://podcasters.apple.com/support/5516-episode-art-template
[apple-chapters]: https://podcasters.apple.com/support/5482-using-chapters-on-apple-podcasts
[apple-artwork]: https://podcasters.apple.com/support/866-promotional-artwork
[apple-transcripts]: https://podcasters.apple.com/support/5316-transcripts-on-apple-podcasts
[apple-links]: https://podcasters.apple.com/support/5536-links-on-apple-podcasts
[apple-submit]: https://podcasters.apple.com/support/897-submit-a-show
[apple-subscriptions]: https://podcasters.apple.com/support/899-set-up-your-show-for-a-subscription
[apple-video]: https://podcasters.apple.com/support/3684-video-podcasts
[apple-hls]: https://podcasters.apple.com/support/5593-how-to-publish-video
[namespace-image]: https://podcasting2.org/docs/podcast-namespace/tags/image
[namespace-images]: https://podcasting2.org/docs/podcast-namespace/tags/images-(deprecated)
[namespace-chapters]: https://podcasting2.org/docs/podcast-namespace/tags/chapters
[namespace-transcript]: https://podcasting2.org/docs/podcast-namespace/tags/transcript
[json-chapters]: https://podcasting2.org/docs/podcast-namespace/examples/chapters/jsonChapters
[podlove]: https://podlove.org/simple-chapters/
[id3-chapters]: https://id3.org/id3v2-chapters-1.0
[lyrics]: itunesdb-lyrics.md
