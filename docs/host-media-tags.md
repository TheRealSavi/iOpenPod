# Host media tag coverage

The Application Layer's `media.tags` adapter interprets native Mutagen values and
FFprobe metadata for Host Media Scan, music import, and Sync enrichment. Scanning
is read-only. Normalized fields survive Host Media Scan Cache v14; versions 9
through 13 migrate while reusing unchanged covered media. Pre-v12 no-cover records
are reinspected once because they did not distinguish absent artwork from an
unreadable embedded image. Tags describe Library classification, not codec
compatibility. See [ADR-0133](adr/0133-recover-evidenced-artwork-without-clearing-unavailable-covers.md).
Pre-v14 Playlist records are reparsed once to restore network filesystem
references and valid POSIX names, including album folders ending in a period;
see [ADR-0083](adr/0083-tolerate-host-native-media-variants.md) and
[ADR-0136](adr/0136-allow-network-filesystems-as-host-media-sources.md).

## Coverage

| Library fields | Representations and common aliases |
| --- | --- |
| Title, artist, album, album artist, genre, year | ID3 frames; MP4 atoms; Vorbis/APE names; ASF attributes; FFprobe names |
| Track/disc numbers and totals | ID3 slash pairs, MP4 integer pairs, `TRACKTOTAL`/`TOTALTRACKS`, `DISCTOTAL`/`TOTALDISCS` |
| Composer, comment, grouping, subtitle, description, copyright, publisher | Native text and named tags; ordinary ID3 comments exclude technical `iTun*` frames |
| Compilation, BPM, release date | Native flags/numbers/dates; fractional BPM truncates to the Library integer |
| Sort title, artist, album, album artist, composer, show | Native names and editor aliases including `ARTISTSORT`, `SORT_ARTIST`, `TVSHOWSORT` |
| Media classification | MP4 `stik`/`pcst`, ID3 `PCST.value`, named `MEDIA_TYPE`/`MEDIA_KIND`/`ITUNESMEDIATYPE`/`PODCAST`; `.m4b` fallback |
| Show, episode ID, season, episode number, network | MP4 TV atoms; ID3 TXXX names; Vorbis/APE and FFprobe aliases |
| Podcast category, feed URL, enclosure URL, keywords | ID3 `TCAT`, `WFED`, `TKWD`; MP4 `catg`, `purl`, `keyw`; explicit named URL fields |
| Unsynchronized lyrics and presence | ID3 `USLT`, MP4 `©lyr`, `LYRICS`, `UNSYNCEDLYRICS`, `UNSYNCED LYRICS`, ASF `WM/Lyrics`, FFprobe language-qualified lyrics |
| Content advisory | MP4 `rtng`, `ITUNESADVISORY`, `CONTENTRATING`; separate from star ratings |
| Rating | ID3 POPM, using the Original iOpenPod's five-star thresholds |
| Normalization gain | Track ReplayGain; valid ten-word `iTunNORM` fallback |
| Gapless Album, purchase account, purchaser name | MP4 `pgap`, `apID`, `ownr`, and editor aliases |

Mutagen documents the native [MP4 value types](https://mutagen.readthedocs.io/en/latest/api/mp4.html)
and [ID3 attributes](https://mutagen.readthedocs.io/en/latest/api/id3_frames.html).
Mp3tag's [field mappings](https://docs.mp3tag.de/mapping/) explain why its
`UNSYNCEDLYRICS` UI field corresponds to native `USLT` or `©lyr`. Literal
`UNSYNCEDLYRICS` in Vorbis comments is also accepted.

## Interpretation rules

Native keys precede aliases. Matching ignores case, spaces, underscores, and
hyphens. The common Library has scalar fields: the first nonempty text value is
used. MP4 freeform text uses its declared encoding; binary objects are never
converted to their Python representation.

Descriptionless nonempty USLT/COMM frames take precedence, followed by description
and language order. Lyrics retain whitespace and line breaks. Native USLT/©lyr
precede named lyrics; `LYRICS` precedes `UNSYNCEDLYRICS`. Multiple POPM ratings use
stable email order. POPM counters are not imported as iPod Listening History.

Explicit Podcast evidence wins. Video roles require files observed or cataloged
as video. Genre, show names, and folders do not imply classification. ID3 `TMED`
describes the original recording medium and is not a Library role. Unknown roles
retain the ordinary audio/video fallback.

Release dates honor explicit offsets. Calendar-only dates use UTC; year/month
precision expands to the first day, following the Original iOpenPod's precision
policy without depending on the Host timezone. Invalid or unrepresentable optional
values leave existing/default fields intact.

When Mutagen provides neither useful tags nor timing for a video file, scanning
tries bounded, cancellable FFprobe metadata inspection on a pinned, seekable Storage
input. This covers containers
such as Matroska and AVI. Container tags precede a preferred playable stream.
Missing tools or failed inspection retain basic facts and a diagnostic. This
fallback avoids copying the whole file. Approved external Playlist references still
use their reviewed private Storage captures. See ADR-0123.
Unreadable audio keeps the existing basic-facts fallback without invoking another
decoder during scanning.

Sync enrichment retains reviewed nonempty fields and specialized classification,
except that nonempty lyrics in the captured Host file supersede reviewed lyrics.
Stock iPod lyrics still require verified embedded text and the database presence
flag under ADR-0075.

## Boundaries and remaining gaps

This covers representable fields rather than every arbitrary Host tag. MusicBrainz
IDs, ISRC, lyricist, conductor, mood, work/movement structure, alternate-language
values, and arbitrary custom fields lack dedicated common representations. Podcast
GUIDs are not enclosure URLs; encoder names are not encoding-quality descriptions.
Synchronized `SYLT` timing is not flattened into unsynchronized lyrics.

Chapters still come from captured FFprobe inspection during preparation. Encoder
delay/padding, sample counts, codec properties, and compatibility remain media
inspection/preparation concerns. Descriptive tags do not override those facts.
Existing iPod ratings and listening history retain the existing Sync Update policy.
There is no new Host tag writing or database schema.

Tests cover native MP3, WAVE, AIFF, FLAC, and MP4 fixtures; APE/ASF wrappers;
video-only MP4 and Matroska; cache reload/invalidation; malformed fields; and real
MP3/FLAC Sync publication. The initial MP3 reproducer failed with `PCST=1` appearing
as Music, matching [Original iOpenPod issue 222](https://github.com/TheRealSavi/iOpenPod/issues/222).
