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
has at most 256 candidates, an application cap rather than a firmware limit.
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

Cold Sync analyzes prepared Host sources and retained iPod music sequentially
through Storage. The normal application keeps a versioned, checksummed, bounded
Host cache of successful compact profiles. Unchanged sources reuse profiles;
changed sources invalidate them. PCM is transient. Decode or cache failure is
reported with metadata fallback, while cancellation, device disconnect, and source
mutation stop preparation. Device identities are checked again before publication.
Synesthesia Track Analysis and Chromaprint matching evidence remain separate.
The current decoder accepts up to 15 minutes of audio and 300 seconds of decoding
time per Track; longer or undecodable Tracks retain metadata candidates. Spectral
and tempo analysis use bounded blocks. The disposable cache is capped at 50,000
records and 64 MiB.

The graph is published with the Library through the existing reviewed Storage
transaction. Classic root `Extras.itdb` is captured, checked, and published with
iTunesDB; late devices use the complete SQLite set. Existing native Mixes and saved
Playlists remain retained. No Mixes, Genius Playlists, or Host playback controls are
created by this workflow. See [ADR-0178](adr/0178-generate-basic-genius-during-sync.md).

## Browsing in iOpenPod

Select an iPod and open **Genius** in the sidebar. The page groups **Genius
Playlists** and **Genius Mixes** and displays their saved Tracks or possible Mix
starting Tracks. Playback controls play only the Tracks explicitly selected;
the iPod's native Mix engine still generates its own playback queue.

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

Retained canonical Genius Playlists preserve their native Smart and seed records
byte-for-byte. Removing their known seed Track while keeping the Playlist is
currently unsupported and blocks analysis. Nonseed Track removal can prune
membership. Ordinary application Playlist controls do not edit these collections.

## Saved Playlists and limits

Unchanged `GeniusPlaylist_N.plist` documents preserve their exact XML/binary bytes.
Edits retain unknown plist values. Classic positions must agree with persistent
IDs and MHIT order; nano identity-only records do not acquire invented indexes.
Raw database timestamps remain unchanged because cross-device epoch semantics are
unestablished. Backup filenames are excluded from capture.

These files are captured for preservation, not imported or consumed. The current
application conservatively allows unchanged/append-only order; removal/reordering
blocks until that workflow supplies persistent IDs to the explicit remapper.
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
