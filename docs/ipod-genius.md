# Native Genius data in iPodDB

iPodDB reads, writes, and preserves Genius data without selecting music or accessing
devices. Device Registry describes firmware capability; iOpenPod owns capture and
publication. See [ADR-0176](adr/0176-preserve-and-author-native-genius-data.md) and the
[format investigation](research/genius-generation-2026-10-24.md).

## Automatic generation during Sync

Sync and Refresh Library regenerate Genius data when the selected iPod supports
native Genius Playlists. The generator uses every music Track in the completed
desired Library, including retained songs and successful additions. Podcasts,
audiobooks, and videos are excluded. Ordinary metadata saves preserve the graph.

Candidate ranking now adapts Elephant-Ear's two-stage selection: compare the body
of each Track, then prefer an intro compatible with the seed's outro among the next
three nearest bodies. Both comparisons remain anchored to that seed; the firmware
still constructs playback. Each present segment has tempo, spectral-centroid mean
and variance, and 13 MFCC means and variances. Ends use 20 seconds each; Tracks of
40 seconds or less use their complete body and have absent ends. An absent end
falls back to body comparison, rather than matching a fabricated silent vector.

Libraries with more than 512 profiles use bounded deterministic projection
neighborhoods; smaller ones use exact body comparisons. Missing profiles use artist, album, and genre
neighborhoods. A Library-wide ring fallback keeps the graph connected. Each Track
has at most 32 candidates, an application cap rather than a firmware limit.
The smaller cap is a playback-latency precaution under
[ADR-0188](adr/0188-bound-authored-genius-candidate-rows.md); native timing and
queue behavior still require hardware comparison.
Retained unique Genius IDs are reused; others are allocated deterministically with
collision checks. See [ADR-0179](adr/0179-rank-genius-with-elephant-ear-audio-profiles.md).

Metadata slots are `[1, artist_key, album_key, genius_id]`. Artist identity and
effective Album Artist retain exact spelling and capitalization; album titles use
the existing case-insensitive equivalence. Missing artist or album identity gets a
Track-specific key. Two opcode-3 rules use `(field, floor, distance, jitter)`:
artist `(1, 1, 6, 2)` and album `(2, 1, 10, 2)`. These are firmware spacing-counter
settings, not exact guaranteed gaps. The compact control suffix is retained and no
skip or category filtering is enabled. Result counts remain 25 desired and 10
minimum. Libraries below that minimum still receive valid relationships, but native
playback is not guaranteed. The new spacing settings require hardware acceptance;
the earlier no-rule experiments do not validate them.

Cold Sync analyzes up to two prepared Host sources or retained iPod music Tracks
concurrently through Storage. The normal application keeps a versioned,
checksummed, bounded Host cache of successful compact profiles. Unchanged
sources reuse profiles; changed sources invalidate them. Cache lookup and source
checks happen before queuing audio work. Only uncached Tracks enter the analysis
step, so a fully cached Sync shows no audio-analysis step. PCM is transient. Each
active Track has its own indeterminate progress bar during analysis; the overall
bar counts only Tracks needing analysis. Decoder and profiler phases do not provide reliable
percentages. Decode or cache failure is reported with metadata fallback, while
cancellation, device disconnect, and source mutation stop preparation. Device
identities are checked again before publication.
Synesthesia Track Analysis and Chromaprint matching evidence remain separate.
The current decoder accepts up to 15 minutes of audio and 300 seconds of decoding
time per Track; longer or undecodable Tracks retain metadata candidates. Spectral
and tempo analysis use bounded blocks. The disposable cache is capped at 50,000
records and 64 MiB.

After a successful Storage commit, profiles computed from prepared Host media are
also cached against the final iPod Track identity and committed file fingerprint.
The published size and SHA-256 must match the analyzed content. This reuses Storage's
verified output evidence without another media read; later lookups still check
the device file identity. Interrupted publication creates no device cache entries.
Failure to save this disposable cache reports a warning without failing an already
committed Sync. Newly added or replaced songs therefore need no second analysis
merely because their source moved from the Host to the iPod.

The graph is published with the Library through the existing reviewed Storage
transaction. Classic root `Extras.itdb` is captured, checked, and published with
iTunesDB; late devices use the complete SQLite set. Existing native Mixes and saved
Playlists remain retained. The graph generator itself creates no collections.
The separate Mix policy below adds explicit manual and automatic collections;
saved Genius Playlist creation and Host Mix playback remain separate. See
[ADR-0178](adr/0178-generate-basic-genius-during-sync.md).

## Adding and rotating Mixes

The Genius Mixes header has Settings and Add glyph buttons. Add opens a grid of
fixed genre and mood proposals, allowing multiple selections. At least ten matching
music Tracks are required for each proposal. Focus, Energy, and Relax use the
existing librosa-derived Genius Audio Profiles to suggest seeds from tempo and
spectral texture. Love also needs a title or album cue; audio cannot determine a
song's subject. Mood counts are checked after audio analysis during save, and a
Mix with too few matching Tracks is rejected without changing the Library.
Add uses the existing Library save
workflow, which saves automatically unless **Draft all changes** is enabled.

Settings stores **Count** (default 0/off) and **Expiry (days)** (default 30) for
the selected iPod. During Sync or Refresh Library, automatic Mixes fill available
slots. A Mix older than Expiry is replaced by a different randomly selected
eligible definition. If no alternative is available, it stays with its original
age. Lowering Count removes excess automatic Mixes at the next Sync; zero removes
all automatic Mixes. Manual Mixes never expire and do not count toward Count.
Selecting an automatic Mix through Add makes it permanent.

The catalog currently covers Rock, Alternative, Pop, Hard Rock, Metal, Punk,
Electronic, Dance, Hip-Hop, R&B and Soul, Jazz, Blues, Country, Folk and Acoustic,
Classical, Reggae, Latin, and Soundtracks, plus Focus, Love, Energy, and Relax.
Genre proposals use genre-tag aliases. Mood proposals require usable audio evidence;
missing profiles do not become matches. These rules do not claim to reproduce
Apple's recommendations. Native relationship traversal can play beyond the
proposed starting Tracks.

Creation requires confirmed native Mix support and a supported SQLite writer.
Other devices continue to browse existing Genius collections. Automatic ownership
is explicit and stored with the Mix publication in
`iPod_Control/iOpenPod/genius-mixes-v1.json`; preexisting unowned collections never
expire. Missing or invalid ownership cannot authorize deletion. See
[ADR-0184](adr/0184-manage-manual-and-automatic-genius-mixes.md).

## Browsing in iOpenPod

Select an iPod and open **Genius** in the sidebar. The page groups **Genius
Playlists** and **Genius Mixes** and displays their saved Tracks or possible Mix
starting Tracks. Playback controls play only the Tracks explicitly selected;
the iPod's native Mix engine still generates its own playback queue.

Select a Genius Playlist or Mix and choose **Remove** to delete that native
collection through the Library save workflow. Removing a Playlist also removes
its matching saved sidecar when present. Removing a Mix clears its iOpenPod
ownership entry, including an automatic Mix. Tracks remain in the Library. An
automatic Mix removed this way may be replaced at the next Sync if Count still
calls for it. Mix removal requires the supported SQLite writer.

`project_genius_browse` combines canonical Genius Playlists, saved plist sidecars,
and optional SQLite Mix records into immutable `GeniusBrowse` collections and
diagnostics. It maps persistent references to existing semantic Tracks and
deduplicates matching native Playlist identities. This separate browse state is
refreshed when loading or saving an iPod. Missing or damaged optional sources do
not prevent primary Library browsing.

Classic MHOD 54 seed records distinguish Genius Playlists from ordinary Smart
Playlists, even when both contain Smart MHODs. Recognized Genius Playlists retain
native data and appear in the Genius browser instead of ordinary Playlist editing.
See [ADR-0177](adr/0177-browse-native-genius-collections.md).

The hardware-confirmed MHOD 54 layout has an eight-byte little-endian seed Track
persistent ID. Other body lengths remain opaque; the marker still prevents Smart
classification. This bounded interpretation comes from the Classic capture, rather
than the Original iOpenPod or libgpod definitions.

## Interfaces

- `iPodDB.genius` provides typed version-2 configuration instructions, metadata
  keys, and uncompressed candidate IDs with parse/serialize functions. Unsupported
  payloads remain `OpaqueGeniusPayload`; malformed known framing raises
  `GeniusFormatError`. Individual payloads are bounded to 16 MiB.
- `iPodDB.library.genius` exports `GeniusData`, row types, `GeniusDatabase`, and
  `parse_genius_database`/`serialize_genius_database`. Documents retain full SQLite
  source bytes; unchanged writes are byte-exact. Classic root `Extras.itdb` and
  late-device `Genius.itdb` share this contract.
- `read_sqlite_genius_state(library, dynamic, genius)` inspects graph assignments
  and native Mixes without altering the Library Snapshot. Returned item references
  are persistent IDs. Optional absent Dynamic Genius columns are supported;
  conflicting present assignments fail.
- `IPodTrackDetails.genius_id` exposes the MHIT relationship identity, distinct
  from `track_id`, `db_track_id`, and `genius_category_id`.
- `iPodDB.sidecars` provides saved Playlist parse/create/write, reference validation,
  and `remap_genius_playlist`. Both Classic positional arrays and nano identity-only
  documents are supported.

## Coordinated writing

Use `library.begin_draft(genius_update=GeniusUpdate(data, tracks, mixes))`, then
analyze and prepare normally. `GeniusTrack(track_id, genius_id)` and
`GeniusMix(container_id, name, track_ids, seed_track_id=None)` use semantic Library
Track IDs. Preparation maps newly allocated IDs. Container IDs are unsigned 64-bit
persistent identities; SQLite represents the high half as signed values. Mix
membership supplies possible starting Tracks, not a complete playback queue.

An explicit update replaces the complete known graph and assignments. Its default
`mixes=None` preserves existing native Mixes while pruning unavailable references;
an explicit tuple replaces the Mix set, and `mixes=()` clears it. Omitting the
entire update preserves retained graph state. Duplicate IDs,
missing Tracks, dangling candidates, incomplete graphs, and incompatible Mix
targets block preparation. Recommendation policy and capability decisions remain
the caller's responsibility.

For selective management, leave `mixes=None` and supply `mix_additions` and/or
`mix_removals`. Additions must have new container identities; removals identify
native Mix containers. All unmentioned native Mix rows retain their original
metadata and Unknown Data. Full replacement and selective edits cannot be combined.

For Classic, supply captured root `Extras.itdb` in `WriteResources.genius_source`
and publish `PreparedLibrary.genius` together with `itunes`. Captured bytes are
required when changing existing Genius identities, preserving unrelated Extras
data. Late devices use the usual `sqlite_sources` and complete
`PreparedLibrary.sqlite`. Signing, CDB framing, reparse verification, and Storage
transaction requirements still apply. Short MHIT layouts without the Genius field
are rejected; this API does not guess header expansion or firmware upgrades.

Metadata edits retain Genius data. Removed/replaced media prunes understood graph
references and Mix seeds; opaque candidate data blocks dependent pruning. Unknown
tables remain opaque. Existing saved-Playlist markers and seeds in SQLite survive;
no unproven MHYP marker or seed field is invented.

Retained canonical Genius Playlists preserve native Smart data and seed records
except for the known seed field when its Track is deleted. Surviving occurrences
keep their order and duplicates; the first remaining member replaces a deleted
known seed. A collection emptied by Track deletion is removed, including its
matching sidecar or Mix ownership. Unaffected empty collections remain retained.
Metadata edits do not reclassify collection membership by genre. Ordinary Playlist
controls still cannot edit native Genius membership or choose arbitrary seeds.
See [ADR-0186](adr/0186-reconcile-genius-collections-after-track-removal.md).

## Saved Playlists and limits

Unchanged `GeniusPlaylist_N.plist` documents preserve their exact XML/binary bytes.
Edits retain unknown plist values. Classic positions must agree with persistent
IDs and MHIT order; nano identity-only records do not acquire invented indexes.
Raw database timestamps remain unchanged because cross-device epoch semantics are
unestablished. Backup filenames are excluded from capture.

These files are captured without import or consumption. The application remaps
supported documents using the prepared Library's final persistent identities and
Track order. It prunes deleted occurrences and repairs a deleted seed, preserving
the remaining selection and unknown values. Changed sidecars and removals publish
with the Library in one recoverable transaction. Unsupported affected formats
still block removal/reordering; unchanged or append-only order preserves them.
Dataset-9 CUID remains opaque. Compressed candidate lists and unknown configuration
operations can be preserved, but cannot be authored as understood data.
Explicit nonempty Classic generation initializes a missing dataset-9 CUID using
the hardware-tested 32-byte ASCII hexadecimal layout. Existing data remains opaque
and unchanged. Its necessity across firmware versions is unproven; full activation
and playback from pristine devices remain hardware acceptance work.

## Validation

Synthetic fixtures cover exact retention, malformed input, unknown data, signed
SQLite identities, schema variants, coordinated updates, Mix retention, and pruning.
Private device captures stay outside Git.

Fresh Classic 6.5G captures contain 162 Tracks, 112 Genius assignments, and 12,432
candidate relationships. Nano 7G captures contain 20 Tracks, 19 SQLite Genius
assignments, 342 relationships, one Mix, and two identity-only saved Playlists.
Payloads and saved documents round-trip exactly. The earlier Classic saved Playlist
contains 25 validated positional/persistent-ID references. Physical replay results
remain separate from these Host checks.

Read-only application selection and rendered Genius page checks against both
connected devices find the Classic's 25-Track `Airbag` Playlist, the nano's two
19-Track saved Playlists, and its 19-starting-Track `iPodDB Test Mix`. All references
resolve without browse diagnostics, and the displayed rows retain collection order.
These checks perform no device publication.

The earlier Library preparation API produced a Classic graph update and a complete
nano CDB/SQLite generation with the Mix renamed to `iPodDB Test Mix`. Both passed
virtual Storage publication and exact rollback, then physical transaction
publication, complete byte-for-byte readback, durability flush, and safe ejection.
The existing saved Playlist sidecars remained unchanged.

Automatic generation during Sync has also passed against fresh captures of both
devices. The full application Sync path ran twice on virtual copies, preserving
Genius IDs, graph contents, and native collections; exact prepared-artifact
publication and rollback restored all captured originals. A subsequent physical
Sync published two Classic files and six nano SQLite files, verified complete
readback, completed recovery cleanup, and safely ejected both iPods. All 112 Classic
music Tracks and all 19 nano music Tracks have generated metadata and candidate
rows. The existing saved Genius Playlists and nano Mix were preserved. Native
playback of this automatic generation was then confirmed by the user: Genius
Playlists generated and played from two different songs on each device, and the
nano's existing Mix played successfully. This validates these two firmware/device
cases; pristine-device activation and other supported models remain untested
physically.
