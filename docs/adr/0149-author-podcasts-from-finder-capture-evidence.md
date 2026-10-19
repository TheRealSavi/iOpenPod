# ADR-0149: Author Podcasts from Finder capture evidence

- Status: Accepted
- Date: 2026-10-18
- Amends: ADR-0037, ADR-0091, ADR-0092, and ADR-0141

> ADR-0151 supersedes this record's audio Podcast media-mask choice. Current
> application writes use type 4; the rest of this decision remains in force.

## Context

The four [Finder captures](../research/podcast-finder-captures-2026-10-18.md)
and [production Sync comparison](../research/podcast-virtual-comparison-2026-10-18.md)
expose identity and metadata gaps. Apple itself omitted native chapter/artwork
data and episode-to-show references. Its bytes are evidence, not a requirement to
reproduce those omissions. The captured MP3s retain covers, chapters, and some
nested chapter pictures that can supply the missing native data.

## Decision

MHOD 15 represents `TrackMetadata.podcast_guid`. Its existing direct UTF-8 payload
encoding stays unchanged. The Podcast GUID is an opaque publisher identifier,
including when it happens to be a URL; the download enclosure is separate.
Podcast imports write the RSS GUID, falling back to the enclosure only when no
GUID exists. MHOD 20 continues to carry the Episode identifier as before.

The application reads older iOpenPod URL-in-MHOD-15/GUID-in-MHOD-20 pairs. Catalog
matching uses exact identities and unique GUIDs. If a publisher has changed both
GUID and enclosure, a unique title and nonzero publication timestamp within the
same feed may bridge the records. Available Episode and season numbers must not
conflict, and both sides must be unique. Ambiguous matches remain separate.
Successful downloads retain their catalog identity and enclosure in the existing
Listening History document, including neutral records for unplayed Episodes.
These records do not mark an Episode listened. They publish with the media and
Library transaction so reconnecting cannot change its local identity.

Audio Podcasts use media mask 5 (Audio plus Podcast) and the existing resume,
skip-shuffle, and Podcast Now Playing policy. As amended on 2026-10-19, Podcast
classification preserves the supplied or retained disc number, including an unset
zero; new Episodes do not receive an invented disc number. This withdraws only the
original disc-1 normalization. Video Podcasts retain their video classification.
Imports derive year from publication time and supply a
modification timestamp. A supplied subtitle becomes MHOD 18; otherwise the first
255 characters of the plain description provide a fallback. The application also
fills these missing display fields on retained Podcasts when publishing a Draft.
Explicit/clean advisory values, Episode numbers, and season numbers remain
supported. Feed declarations of `yes`, `true`, `no`, `false`, and `clean` are
recognized, with Episode declarations overriding show defaults.

New or affected Podcast album groups use MHIA `content_type_flag=3`; music groups
continue to use 2. One album row per show remains the authoring policy. There is
no requirement to duplicate Apple's two rows per show or normalize untouched rows.

SQLite derives Podcast identity, media flags, and descriptions from the checked
CDB. `podcast_info.external_guid` receives MHOD 15, the Podcast container uses
`distinguished_kind=11`, and its media mask is the union of its members. The Master
container likewise carries the union of Library media. Short and full Podcast
descriptions populate `description` and `description_long` separately. Existing
dataset-5 firmware categories remain supported under ADR-0141.

Sync explicitly requests repair of missing episode-to-show links. The resolver
describes this as a Playlist repair even when semantic membership is unchanged,
groups Episodes by show, and verifies native references and positions after
serialization. Existing identity ambiguity still blocks repair. Ordinary iPodDB
no-op preparation and serialization preserve the original bytes exactly.

As amended on 2026-10-19, affected dataset-3 Podcast rows have strictly increasing
native row IDs in serialized order: each show group precedes its Episodes both
physically and numerically. An already ordered prefix retains its IDs; rows that
would break the order receive new IDs above all existing MHIP row IDs, with later
rows following them. Episode parent references follow the resulting group IDs.
Dataset-2 counterparts receive matching Episode row IDs, retaining their own
order, persistent identities, and private metadata. Retained empty groups
remain after populated groups and participate in numbering. Explicit Podcast
repair also detects backwards or missing row IDs even when parent links exist.
This follows the [captured numbering convention](../research/podcast-finder-captures-2026-10-18.md#podcast-playlist-structure-and-root-hypothesis);
Finder acceptance remains a separate device test.

The later Apple PlayCount capture retains Episode type-100 positions from older
row IDs in both datasets even after Apple renumbers the rows. Accordingly, row
repair preserves the dataset-2 position and copies it to the matching dataset-3
Episode instead of replacing it with the new row ID. Repeated Tracks pair by
occurrence order. A missing flat position falls back to the grouped value; only
when neither exists does the new row ID supply a position. Creating a missing
flat counterpart also preserves the grouped positions. Membership edits continue
to regenerate consecutive positions, now shared by both counterparts. Explicit
repair detects mismatched or missing positions, and verification checks agreement
between counterparts independently of row numbering. Finder acceptance of this
change remains untested.

New special Podcasts Playlists use Playlist Sort Order Title (native value 3).
When an existing special Playlist is affected by edits or group repair, its unset
sort order becomes Title; explicit nondefault orders remain retained. Missing
MHOD 102 settings receive the identical 332-byte payload captured in all seven
dataset-2/3 Podcast counterparts across the four models. The four nonzero words
remain opaque; their meaning is not inferred. Existing settings, including unknown
bytes and extensions, remain untouched. Both flat and grouped counterparts receive
the settings, while episode membership retains the existing grouping policy.

As amended on 2026-10-19, Master MHOD 52 / sort 36 treats wholly Podcast album
groups as newest first by publication date, with missing dates last and retained
order breaking ties. This is independent of the special Playlist's MHYP sort
order and leaves sort 4 and non-Podcast disc/track ordering unchanged. The
[sort-36 investigation](../research/itunesdb-sort-36.md#podcast-member-order-investigated-on-2026-10-19)
matches all four useful Apple captures but cannot distinguish publication date
from descending track number; date precedence and missing-date behavior are
explicit authoring choices. Unchanged indexes remain byte-exact.

The Application Layer supplies one captured UTC Unix timestamp through
`WriteResources.playlist_timestamp`. Affected Podcast Playlists retain a nonzero
creation timestamp and receive the captured modification timestamp; new Playlists
receive both. iPodDB uses the established Device Time Context conversion and never
reads the Host clock. Callers supplying no timestamp retain date fields. Unchanged
preparation remains byte-exact even when a later timestamp is supplied. This
extends ADR-0024's new-Playlist timestamp consistency with actual clock evidence.

Embedded cover import precedes publisher cover fallback. ID3 CHAP/APIC pictures
from the original captured download become explicit timed artwork using ADR-0139's
writer and configured cover/chapter formats, including after transcoding. Only
recognized chapter positions are eligible. Text chapters retain duplicate start
times; at each image time the first decodable picture in element-ID order wins.
A chapter picture at zero supplies the initial image; otherwise the cover does,
falling back to the first valid chapter image if no cover exists.

The chapter reader bounds ID3 tags to 16 MiB and individual encoded pictures to
8 MiB. Decoded covers and chapter images share the existing 64 MiB Podcast batch
budget. Invalid pictures produce warnings while valid media, chapters, and other
images remain usable. It does not fetch URL-linked chapter images.

## Consequences

No dependency or database schema is added. Filesystem access remains in Storage;
iPodDB receives owned metadata and pixels. Existing Sort Album and lyrics behavior
is retained. Regression tests cover legacy identities, GUID changes, advisories,
neutral history across reconnects, missing-link repair, SQLite classification,
album flags, timed images through direct-copy and transcoding paths, and Podcast
playlist settings, date conversion, retained settings, and unchanged round trips.

The four virtual devices provide binary and transaction verification. They do not
establish physical firmware playback behavior, including whether these repairs
resolve the reported Classic “Root” display.
