# Library contract

`iPodDB.library` is the public data interface for library consumers. GUI and
application models use `LibrarySnapshot`, Track and Playlist records, and the
optional `PhotoLibrary`. They do not import iTunesDB, ArtworkDB, or PhotosDB
internals.

## Constructing a snapshot

A source adapter can construct the same records without an iPod database:

```python
from iPodDB.library import LibrarySnapshot, MediaType, Track, TrackMetadata

snapshot = LibrarySnapshot(
    tracks=(
        Track(
            track_id=1,
            title="An episode",
            artist="A narrator",
            album="A series",
            length_ms=120_000,
            media_types=(MediaType.PODCAST,),
            metadata=TrackMetadata(sample_rate_hz=44_100, remember_position=True),
        ),
    ),
)
```

The Host Media Library scanner is one such adapter: it publishes audio and video as
`Track` records, Photos through `PhotoLibrary`, and supported Playlist files through
`Playlist` and `PlaylistEntry`. It retains Host paths and cache facts in its
source-specific `HostMediaLibrary` wrapper. Track source records also retain the raw
Chromaprint fingerprint produced during the scan; it is matching evidence, not common
Library metadata. The same tuple feeds the existing Track, Album, and collection
models; source-specific workflows still decide whether Queue, History, editing, or
export is authorized. No remote connector is implemented by this interface alone.

The Sync Workspace browses the completed Host snapshot through separate, read-only
instances of the same Library pages and models used for an iPod Library. It never
loads that snapshot into the Active iPod's Library Workspace or exposes it as a
normal-sidebar Library Source. Host Photo pixels are read lazily through the source
adapter and accepted only while their observed size and modification time still match
the completed scan. See ADR-0064 and ADR-0067.

- Track IDs uniquely identify items within one snapshot; duplicate IDs raise
  `ValueError` during snapshot construction, including iPod source loading. Track
  IDs are opaque and zero is valid. Artwork IDs identify covers within that source;
  an artwork ID of zero means no known cover. Source adapters retain their own
  native-ID mapping and authenticated access state.
- Durations and chapter positions use milliseconds; dates use Unix seconds, with
  zero for missing or unresolvable dates. Unresolvable device dates retain their
  native bytes and produce diagnostics; see [timestamp conversion](ipod-time.md).
  File sizes use bytes and sample rates use hertz.
- Ratings retain the existing 0–100 application scale. Volume adjustment is a
  percentage; normalization gain is decibels or `None` when absent. Positive gain
  amplifies and negative gain attenuates. Pre-gap and post-gap values count samples.
- Flags are booleans, content advisory is an enum, and media types are a tuple of
  semantic enums. `media_kind` provides the existing browsing category.
- `Track.ipod` defaults to `None`. Its typed diagnostic values are useful for iPod
  inspection columns but are not prerequisites for browsing or playback policy.
- Metadata locations are descriptive values, not permission to open a file or URL.
  For an iPod source, the adapter normalizes colon-delimited locations to relative
  slash-delimited paths; Storage still validates containment and identity.

## Playlists

`LibrarySnapshot.playlists` contains immutable `Playlist` records. Each has a
unique opaque `playlist_id`, name, semantic `PlaylistKind`, optional `parent_id`,
ordered `entries`, optional `SmartPlaylist` configuration, description, and typed
`PlaylistSortOrder`. Read-only `system_managed` source metadata does not participate
in draft equality. The iPod adapter sets it for the firmware-maintained Podcasts
Playlist; the GUI omits that record from the sidebar tree while the Library Snapshot
and Library Workspace retain it for reconciliation.
`None` is the sidebar root; only `PlaylistKind.FOLDER` can parent another record.
Common IDs may be zero. The iPod adapter translates its zero parent sentinel to
`None`, resolves invalid hierarchy links for display, and retains source bytes.

Each `PlaylistEntry` contains a stable occurrence identity, a Track ID, and the
optional zero-based Playlist Position parsed from its MHIP type-100 child. The GUI
presents that position as a one-based Track-table value. `track_ids` is derived
from entries: repeats and saved order matter. Changing an understood Playlist Sort
Order stably reorders occurrences and refreshes their consecutive positions.
Unknown MHYP sort values use `UnsupportedPlaylistSortOrder`, remain visible to API
consumers, and round-trip without invented semantics. Smart
rules are independent of that saved list, so loading a snapshot does not evaluate
or rewrite membership. Unknown rule conditions are represented explicitly and
make the configuration uneditable. Nested groups retain their own conjunction.
Ratings use the common 0-100 scale. Limits state units and sorting semantically.
Playlist references, Media Kind, and Location use typed semantic choices rather than
native IDs or bit masks. See
[ADR-0035](adr/0035-author-evidence-backed-smart-playlist-choices.md).

`LibrarySnapshot.device_name` comes from one eligible Master Playlist, otherwise
it is empty. `ActiveIPod.display_name` prefers it to the candidate's name.
Artwork replacement retains both the name and the Playlists.

The Library Workspace applies changed Smart Playlist rules and matching entries
together. Pure previews and unchanged rules leave saved membership intact. An
explicit Evaluate now action can refresh one supported Smart Playlist's saved
membership against the current draft. Draft edits do not alter the source adapter
or its serialized bytes. Review Changes can prepare and then save metadata,
device-name, and Playlist output with unchanged media and artwork; verified saving
adopts a new source.
See [ADR-0026](adr/0026-share-one-library-workspace-for-metadata-and-playlists.md).

## Photos

`LibrarySnapshot.photos` is either `None` when no usable PhotosDB was loaded or an
immutable `PhotoLibrary`. It contains ordered `Photo`, `PhotoAlbum`, and
`PhotoFileFormat` records. A Photo owns semantic dates, rating, source-size
diagnostics, and typed full-resolution or thumbnail representations. Representation
locations are descriptive device-relative paths; they do not authorize file I/O.

Photo Albums expose ordered Photo membership, album role, slideshow timing and
flags, and an optional slideshow-music Track reference. Native album diagnostics
remain in `IPodPhotoAlbumDetails`. The Library Workspace exposes these records and
uses the same revision-checked, complete-snapshot draft contract as Tracks and
Playlists.

Current semantic writing supports retained Photo rating and date edits; retained
user-album naming, membership, slideshow preferences, and slideshow music; and
explicit creation and deletion of a user album. It also supports deletion of retained
Photos with explicit omission intent: every Album occurrence is removed, and the
Master Photo Album changes only by that exact consequence. A new Photo Album is
empty, appended after retained albums, and carries the selected Device Profile's
non-master MHBA creation type. Adding Photos, editing or deleting the Master Photo
Album directly, changing representation storage, and changing file formats remain
blocked until asset allocation policies exist. These limits are enforced again
during preparation, not only by the UI.

## Reading an iPod source

```python
from iPodDB.library import IPodLibrary

source = IPodLibrary.parse(itunes_bytes)
source = source.with_artwork(artwork_bytes)  # when optional artwork metadata exists
source = source.with_photos(photos_bytes)  # when optional PhotosDB metadata exists
snapshot = source.snapshot
```

The adapter owns parsing, typed Chunk traversal, timestamp and flag conversion,
FourCC fallback, ArtworkDB-to-Track relationships, and PhotosDB projection.
`DeviceCoordinator` keeps the adapter privately while publishing only `snapshot`
in Active iPod state.
Both `IPodLibrary(itunes_bytes)` and `IPodLibrary.parse(itunes_bytes)` accept bytes;
its constructor does not accept Database Documents or a separately built snapshot.
The `snapshot` property is read-only. `with_artwork` and `with_photos` return new
adapters with new source revisions and leave the original source and snapshot
intact.

For a visible cover, `source.artwork_read(artwork_id, formats, target_px)` selects the
smallest suitable source representation, or the largest available smaller one.
The caller supplies typed `CoverFormat` capabilities and receives an `ArtworkRead`
with a relative path, offset, length, and format identity. It validates the range
and reads through Storage, then calls `read.decode(payload)` to obtain RGB888
pixels. Neither the snapshot nor the GUI receives an Artwork Index or iTHMB layout.
No cover pixels are read or decoded during snapshot construction.

Photo thumbnails use the parallel
`source.photo_read(photo_id, formats, target_px)` contract. The Application Layer
supplies typed Photo formats from the selected Device Profile, validates that the
returned range remains beneath `Photos/`, reads that exact range through Storage,
and calls `decode`. `DeviceCoordinator.load_photo` returns an immutable RGB888
`PhotoImage` for UI use; no PhotosDB Chunk, iTHMB layout, Mount Point, or Filesystem
Session crosses that seam.

`source.serialize()` returns retained iTunesDB, optional ArtworkDB, and optional
PhotosDB bytes through the existing lossless writers. Snapshot edits do not edit
those documents.
For semantic edits, submit a complete snapshot through `begin_draft`, `analyze`,
and `prepare`. These retain the source, return structured diagnostics and optional
verified output, and perform no filesystem access. Omitting source Tracks,
Playlists, Photos, or user Photo Albums is blocked unless the draft explicitly
enables `delete_omissions`. See
[Library writing](library-writing.md) and ADR-0021. Physical Sync still requires
the established Storage transaction workflow.
