# Glossary

This glossary defines the language used in iOpenPod documentation, conversation,
tests, and code. Preserve established brand spelling wherever practical: **iOpenPod**,
**iPod**, **iPodDB**, **iTunesDB**, **ArtworkDB**, and **PhotosDB**. Do not respell these as
“IOpenPod,” “Ipod,” or “Itunes.” Generic Python package and module names follow
normal lowercase conventions while retaining the same domain term.

## Product and actors

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **iOpenPod** | The desktop product that manages an iPod without iTunes. | iOP, the program, the tool |
| **Original iOpenPod** | The existing iOpenPod project whose behavior, research, tests, and fixtures form the compatibility baseline for iOpenPod 2.0. It is evidence, not a runtime dependency. | old app, legacy codebase |
| **iOpenPod 2.0** | The deliberate rebuild in this repository, developed toward parity with and then beyond the Original iOpenPod. | rewrite when the version matters, MVP |
| **Host** | The computer running iOpenPod. | PC when referring to all platforms, client |
| **iPod** | A supported Apple media device whose library is accessible through the Host filesystem. | player, drive, generic device |

## Device identity and storage

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Physical Device** | A hardware storage device connected to the Host. | disk, drive, iPod when the generic storage object is meant |
| **Device Identity** | Stable evidence used to distinguish one Physical Device from another. | path, drive letter, mount name |
| **Volume** | A filesystem-bearing logical storage unit exposed by a Physical Device. | partition when no partition is known, drive |
| **Volume Identity** | Stable evidence used to distinguish one Volume from another. | Mount Point, drive letter |
| **Mount Point** | The temporary Host path at which a Volume is accessible. | Device Identity, Device Path |
| **Device Path** | A validated relative path inside an authorized device filesystem root. | Host path, absolute path, file path |
| **Filesystem Session** | Authorized access to one connected Volume for one Connection Generation. | mount, handle, device connection |
| **Connection Generation** | The unique lifetime of one attachment of a Physical Device. | session, connection ID |
| **Storage Transaction** | A planned unit of filesystem change that is validated, executed, verified, and committed together. | sync, batch, file operation |
| **Operation Journal** | A durable record of the intended and completed steps of a Storage Transaction. | log, history |
| **Backup Snapshot** | A user-controlled record of one iPod file tree whose immutable file catalog and verified content can be restored or exported from a Host archive. Its descriptive note may change. | backup when referring to the workflow, rollback |
| **Backup Identifier** | The serial-first value used to associate Backup Snapshots with an iPod. It uses a hashed product or transport serial when known and a hashed Volume Identity as a best-effort fallback. | stable Device Identity, Archive Key |
| **Backup Archive** | An iOpenPod Host repository containing verified Backup Snapshots and deduplicated content. Backup format v4 continues the Original iOpenPod v2 and v3 sequence. Its Archive Keys locate data but never authorize device mutation. | backup folder, Original archive |
| **Legacy Backup Import** | A read-only conversion of a verified Original iOpenPod backup format v2 or v3 archive into Backup Archive format v4. | migration when no source conversion occurs, opening an Original archive in place |
| **Restore Recovery** | The required continuation of a restore whose journaled device publication began but did not reach verified durable completion. | retry, automatic rollback |
| **Active iPod** | The one iPod currently loaded by iOpenPod, chosen by the user now or restored from the user's previous selection. Other connected iPods may be discoverable but are not active. | current drive, selected path |
| **Device Candidate** | The path-free Application Layer description of one currently discovered iPod-shaped Volume containing `iPod_Control`, its Identification Result, and whether it can become the Active iPod. It is not an authorization to perform device I/O. | drive entry, mount path, active device |
| **Device Picker** | The GUI through which the user chooses the Active iPod from discovered or manually located candidates. | drive picker, mount selector |

## Device identification

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Device Registry** | The canonical catalog and lookup boundary for known iPod identities and capabilities. | Device-Registry in prose, device database, hardware service |
| **Device Identifier** | A normalized hardware, firmware, USB, model, or serial value used for registry lookup. | device ID when the identifier kind is important |
| **Device Evidence** | An immutable collection of typed Device Identifiers, their provenance, and whether they came from current hardware, device metadata, or derivation. | device dict, scan result, untyped metadata |
| **Identification Result** | The Device Registry's immutable answer containing identification status, connection mode, an optional exact Device Profile, bounded candidates, and structured conflicts. It does not authorize device I/O. | detected device, active device, write-safe device |
| **Device Profile** | The structured description of one recognized iPod model and generation. | device dict, model object, metadata blob |
| **Device Capabilities** | The structured set of behaviors and formats supported by a Device Profile. | flags, model checks, feature booleans |
| **Hardware Probe Observation** | A generic, current Host observation such as SCSI vendor, product, firmware, unit serial, vendor payload bytes, or opaque device-manager properties. Storage reports it without assigning iPod semantics. | probe dict, detected model, SysInfo |
| **Device Metadata Reconciliation** | The selection-time Application Layer workflow that analyzes ranked Device Evidence, plans desired SysInfo metadata, uses Storage for atomic writes, verifies the result, and records provenance. | scan, Sync, unconditional rewrite |
| **SysInfo Authority** | The version-1 `iOpenPodSysInfoAuthority` record beside SysInfo. It records per-field values and provenance plus hashes used to detect external metadata changes. | source cache, hardware truth, database authority |

## Libraries and databases

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Host Media Library** | The media collection on the Host that may be compared with an iPod Library. | PC library, source folder, local library |
| **Host Media Scan** | The read-only Application Layer workflow that enumerates the user-selected Host Media Library folders, reuses unchanged cached metadata, resolves explicitly accepted external Playlist references, and publishes an in-memory Library Snapshot. It stops before comparison or Sync planning. | import, Sync, folder crawl |
| **Host Media Scan Cache** | An application-owned, checksummed catalog of source path, media kind, size, modification time, inspected metadata, Track Acoustic Fingerprints, Host artwork references, and Photo Image Content Fingerprints used to avoid rereading unchanged files during a Host Media Scan. It is an optimization, never Library authority. | Host Media Library, Backup Snapshot, source of truth |
| **Acoustic Fingerprint** | The bounded raw Chromaprint algorithm-2 sequence calculated by `fpcalc` for a Host audio or video Track. It is source-specific matching evidence retained outside the common Library Snapshot. | content hash, metadata identity, file fingerprint |
| **Image Content Fingerprint** | The SHA-256 digest of one Host or iPod full-resolution image file, used as exact-byte matching evidence. It does not claim that a resized, re-encoded, or packed iTHMB representation is the same content. | perceptual hash, Artwork ID, Photo ID |
| **iPod Media Scan** | The pre-Sync Application Layer workflow that inspects the Active iPod's Library files after Host Media Scan, reuses valid Library Sync Helper entries, and fingerprints only missing or stale Tracks and full-resolution Photos. | device discovery, iPod Library load, Sync execution |
| **Library Sync Helper** | The versioned, checksummed `iPod_Control/iOpenPod/library-sync-helper.json` correlation index from persistent iPod Track IDs and Photo IDs to fingerprints, device-file facts, and optional proven Sync Details. It is an optimization and never Library or mutation authority. | iTunesDB, Host Media Scan Cache, source of truth |
| **Sync Details** | Provenance recorded for one Track or image only after a successful Sync commit, including the Sync time and the corresponding Host file's path hint, size, modification time, formats, and conversion status. | scan time, cached file identity, Sync Plan |
| **Sync Plan** | An immutable, review-only Application Layer account prepared from completed Host and iPod Media Scans. It classifies uniquely correlated Tracks and full-resolution Photos as Add, Update, Remove, or In sync, while unsafe correlations remain Needs attention. It neither authorizes nor performs device mutation. | diff, command list, Sync execution |
| **Sync Plan Item** | One Track or Photo comparison in a Sync Plan, including its proposed action, Host and iPod identities, and typed matching basis. | table row when the domain result is meant, file operation |
| **Sync Selection** | Mutable Application Layer intent over one immutable Host/iPod comparison. Correlated Host items start selected, Host-only items start unselected, and iPod-only removal candidates remain separate until Review. Final Review exclusions skip proposed actions without changing desired Host membership. | edited Library Snapshot, mutable Sync Plan, checkbox state in widgets |
| **Sync Workspace** | The staged full-window GUI surface for source scanning, Host media selection, Review, execution, and recovery results. It opens after the modal media-folder dialog is accepted, temporarily replaces the normal central content, and does not add a Host source to the normal sidebar. | Host Library tab, Sync Plan page |
| **Sync Review** | The GUI stage that presents the selected Sync Plan and unchecked iPod-only removal candidates before the user authorizes validation and execution. | confirmation dialog, Sync Plan, Library Review |
| **Sync Execution** | The Application Layer workflow that validates a reviewed selection, prepares media on the Host, reconciles one isolated Library Draft, publishes verified changes through Storage, and records successful Sync Details after commit. Independent preparation failures may yield partial completion; interrupted publication requires recovery. | file copying, transcoding when referring to the whole workflow |
| **Media Inspection** | Immutable observed container, stream, timing, chapter, and tag facts tied to captured Host file content. It does not choose a Track's Library classification, establish Device Profile compatibility, or authorize publication. | imported Track, codec approval, file extension |
| **Media Content** | Caller-observed audio, video, audio/video, or document content supplied with Prepared Media. It determines required timing facts independently of the Track's Library classification; embedded cover images are not timed video. | Media Kind, Media Type, filename extension |
| **iPod Library** | The media collection represented by an iPod's files and databases. | device library, database, iTunes library |
| **Library Snapshot** | An ordered, immutable collection of Tracks and Playlists with an optional Photo Library and device name. It can be constructed by an iPod or another Library Source and contains no Database Document, Artwork Index, or transport handle. | parsed database, mutable library, model copy |
| **Playlist** | A named, ordered collection of Track occurrences. The same Track may occur more than once. | Track set, queue when referring to a saved collection |
| **Playlist Entry** | An occurrence of a Track with an opaque identity and optional zero-based Playlist Position scoped to its Playlist and source revision. Duplicate Tracks have distinct entries and retain their own private metadata. | Track ID when referring to an occurrence |
| **Playlist Sort Order** | The saved rule that determines the order of a Playlist's entries, such as Manual, Title, Album, or Artist. It is distinct from a temporary Track-table sort. | table sort, Smart Playlist limit sort |
| **Playlist Position** | The zero-based position stored on a Playlist Entry. The GUI presents it as a one-based number. Podcast grouping may use a firmware-specific native value instead. | Track number, table row when the stored value is meant |
| **Library Draft** | A complete desired Library Snapshot bound to the opaque revision of its retained source documents. It can explicitly request media replacement for retained Tracks even when projected metadata is unchanged. Omitting a previously projected Track or Playlist requests deletion, which requires an explicit opt-in for that draft. | mutable database, patch list |
| **Library Resolution** | An immutable account derived from a Library Draft: effective semantic values, generated changes, native consequences, causes, and preservation constraints. It is observable but cannot be submitted as a separate editable draft. | command list, mutable plan |
| **Write Effect** | A generated consequence of requested Library changes, with its affected subject, reason, and references to those requested changes. Exact resource-dependent bytes and identities are established by preparation. | implicit repair, writer command |
| **Library Preparation Request** | An immutable Application Layer capture of desired Library state, its loaded Active iPod, workspace generation and edit revision, and omission-deletion policy. It requests preparation, not a physical save. | save command, mutable draft, patch list |
| **Prepared Library** | Verified candidate iTunesDB or iTunesCDB bytes, optional SQLite Library Artifact Set, ArtworkDB and PhotosDB bytes, changed artwork-file bytes, retained source dependencies, resulting snapshot, and allocated identity mappings. Preparation does not save files or mark a draft saved. | synced library, saved database |
| **Smart Playlist** | A Playlist with rules and selection preferences, separate from its saved Track membership. | filter when referring to the saved Playlist |
| **Playlist Folder** | A named container for Playlists, Smart Playlists, and other Playlist Folders. | group when referring to the sidebar container |
| **Master Playlist** | The iTunesDB library-wide Playlist whose title names the iPod. It is not an ordinary user Playlist. | root folder, firmware category |
| **Library Workspace** | Application-owned session drafts for the Active iPod's Track metadata, device name, Playlists, and Photos. It retains the loaded Library Snapshot and produces one complete desired snapshot without writing database bytes. | Playlist Workspace, writer model, saved changes |
| **Library Source** | The adapter that translates one source's records into a Library Snapshot and retains the source-specific identity and access information needed to load media, artwork, or Photo thumbnails. | database document, GUI model |
| **Track** | One playable media item represented in a media library. | song when the item may be spoken word or video, file |
| **Chaptered Track** | One playable Track with named time positions that let the iPod navigate sections of its media. Album conversion makes one Chaptered Track from a complete saved Music Album. | Playlist, collection, multiple Track files |
| **Podcast Subscription** | A user-added or device-recovered Podcast feed retained in the Active iPod's versioned iOpenPod metadata. Its document stores show-level metadata but neither Podcast Episodes nor current device membership. | feed row, Podcast Playlist, downloaded show |
| **Podcast Episode** | One Podcast publication identified across RSS and iTunesDB by enclosure URL, GUID, or bounded fallback evidence. Its current `on_device` state is projected from the Active iPod. | Track when the feed publication is meant, download |
| **Listening History** | Persistent per-episode Podcast state independent of Podcast Subscriptions and current iPod membership. It retains observed play facts, an optional explicit listened/unlistened override, publication chronology, and exclusions for successful automatic clears. An exclusion does not mark an Episode listened or advance the chronological listening position. | Playback History, play queue, subscription state |
| **iPod Track Details** | Optional typed diagnostic values associated with a Track read from an iPod. They are separate from the common metadata and are not required for Tracks from another Library Source. | universal metadata, arbitrary extras |
| **iTunesDB** | The primary family of iPod database formats that represents tracks, playlists, and related metadata. | database, library file, iPodDB |
| **iTunesCDB** | The late-iPod physical form of iTunesDB whose root header remains uncompressed while its child extent is one zlib stream. It uses the same logical Chunk document and is signed only after compression. | compressed database, SQLite database |
| **SQLite Library Artifact Set** | The coherent late-iPod firmware projection consisting of Library.itdb, Locations.itdb, Dynamic.itdb, Extras.itdb, Genius.itdb, and Locations.itdb.cbk. It is generated solely from the checked iTunesCDB Library Snapshot and published as one replaceable generation; it is not read into the Library. | SQLiteDB, one SQLite file, iTunesCDB, Library authority |
| **Locations Checksum Book** | `Locations.itdb.cbk`, containing SHA1 checksums for 1024-byte Locations.itdb blocks, their aggregate SHA1, and the Device Profile-required signature envelope. | CBK when its role is unclear, database signature |
| **ArtworkDB** | The iPod database format that indexes artwork records and image data. | artwork database file, image library |
| **PhotosDB** | The iPodDB artifact API for the on-device `Photos/Photo Database`, which indexes photos, albums, full-resolution image references, and photo thumbnail data. Its nested Chunk grammar overlaps ArtworkDB, but its root type and Database Definition are distinct. | PhotoDB, ArtworkDB when the Photo Database artifact is meant |
| **Photo Library** | The optional source-neutral collection of Photos, Photo Albums, and Photo file formats in a Library Snapshot. It contains semantic records and descriptive relative locations, not a PhotosDB document or filesystem authority. | PhotosDB, image library |
| **Photo** | One semantic image record in a Photo Library, including dates, rating, and its retained full-resolution or thumbnail representations. | artwork, cover |
| **Photo Album** | One named, ordered collection of Photo identities with slideshow preferences. The Master Photo Album is firmware-significant and is not an ordinary user album. | Playlist, Artwork album |
| **Artwork Index** | The immutable iPodDB projection that maps ArtworkDB image IDs and Track database IDs to bounded iTHMB locations. | artwork cache, image dict |
| **iTHMB** | A device-specific image file containing packed cover or Photo pixels referenced by ArtworkDB or PhotosDB byte ranges. | thumbnail database, album-art file |
| **Chunk** | A tagged binary record used within an iPod database format. | block, object, node |
| **Chunk Definition** | The immutable, header-typed binary contract for one known Chunk, including its Header Marker, extent, body kind, header sizes, fields, and allowed children. | chunk metadata, header map, parser config |
| **Database Definition** | The one immutable, root-typed aggregate of all Chunk Definitions and MHSD dataset definitions for iTunesDB, ArtworkDB, or PhotosDB. Parsers and writers share it. | registry, parser config, writer config |
| **Database Document** | The immutable, root-header-typed Chunk tree returned by an iPodDB parser, persistently edited by a consumer, and accepted directly by the matching writer. | final data structure, parsed database dict, writer model |
| **Chunk Selection** | A root-and-header-typed location and Chunk within one Database Document state. It lets a consumer replace a nested Chunk without reconstructing its ancestors. | cursor, loose path, node reference |
| **Header Marker** | The four-character tag that identifies a Chunk's binary record type. | magic, header, chunk name |
| **Unknown Data** | Fields, Chunks, flags, padding, or bytes that iPodDB can retain but does not yet understand. Unknown Data is expected and is not synonymous with malformed data. | garbage, corruption |

## Application workflows

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Sync** | The user-directed, primarily Host-to-iPod workflow that reconciles a Host Media Library with an iPod Library and may include supported iPod-to-Host updates. | copy, import, transaction |
| **Sync Plan** | An immutable proposal of additions, removals, updates, and conversions for one Sync. | diff, changes, queue |
| **Sync Review** | The user-facing examination and selection of operations in a Sync Plan before execution. | confirmation, preview, plan |
| **Playback Entry** | One runtime identity for a Track occurrence selected from the Playback Queue or Playback History. Duplicate occurrences of the same Track have distinct Playback Entries. | Track ID, Queue row, Playback Attempt |
| **Playback Queue** | The runtime-only ordered occurrences of Tracks that are waiting to start. Each occurrence has its own session identity, so duplicate Tracks can be reordered or removed independently. The current Track is not part of the Playback Queue. | playlist, Sync queue, current Track |
| **Playback History** | The runtime-only, newest-first record of every Track start in the current application session. Traversing an existing entry does not record it again. | listening log, persistent history, recently added |
| **Playback Backend** | A replaceable Application Layer adapter that decodes media, drives audio output, and reports transport events without owning Queue, History, or Player behavior. The current implementation adapts Qt Multimedia. | player widget, playback UI, Playback Service |
| **Playback Source** | A seekable, read-only view of a requested Track's encoded bytes. For an iPod Track, it is bound to the Active iPod's Filesystem Session and source identity and exposes neither a Mount Point nor an absolute Host path. | file path, media URL, byte copy |
| **Musical Evidence** | One typed time-varying measurement or discrete event inferred from a complete audio file, including its reliability, validity, calibrated meaning, timing, and provenance. It contains no rendering response or force policy. | FFT bin, visualizer control, shader setting |
| **Source Analysis** | An ephemeral acoustic family or learned instrument Source represented by source-local Musical Evidence, confidence, and provenance. A separated waveform is intermediate evidence and is not persisted. | stem file, Track, channel |
| **Track Analysis** | The immutable, runtime-only result of a Musical Analysis Job. It aligns calibrated energy, rhythm, spectrum, timbre, harmony, space, layers, Sections, events, and Sources on one sampling interface with explicit validity and confidence. | World Score, cache, visualization preset |
| **World Score** | The removed exploratory Synesthesia analysis contract. It remains historical terminology only; the current backend produces Track Analysis without a compatibility envelope. | Track Analysis, force map, visual preset |
| **Musical Analysis Job** | An Application Layer workflow that independently decodes one requested Track's encoded media and creates fresh in-memory Musical Evidence. It borrows identity-bound media access but neither controls Playback nor retains its temporary encoded copy, PCM, stems, embeddings, or evidence. | playback session, scan, cached analysis |
| **Field Conductor** | The renderer-neutral presentation component that samples Track Analysis at the current Transport Epoch, applies force-specific response policy, and produces Field Forcing. | renderer, analyzer, effect selector |
| **Synesthesia Preview** | The immediate, presentation-only field motion for a current Playback Entry while Track Analysis is pending. It follows the Player clock and Track identity without reading audio or claiming Musical Evidence. | Musical Analysis Job, beat estimate, cached analysis |
| **Mood Signature** | A presentation-owned vector derived from calibrated energy, brightness, harmony, percussion, bass, stereo width, and noise. It directs visual Scene choice without claiming emotion, genre, lyrics, or intent. | emotion label, Musical Evidence, genre classifier |
| **Scene Director** | The frontend presentation component that plans stable, mood-weighted visual Scene residences, Camera Shots, and transitions across a Track. | analyzer, random preset timer, renderer |
| **Camera Shot** | One bounded, seek-stable composition inside a visual Scene residence. It has an editorial kind, identity, position, target, roll, lens, and musical timing selected by the Scene Director. | zoom pulse, camera preset, Scene Motion |
| **Scene Motion** | The stable world choreography assigned to one visual Scene residence: travel direction, travel rate, orbit, depth velocity, waveform deformation, parallax, and world scale. | elapsed-time drift, Musical Evidence, Camera Shot |
| **Visual Scene** | One named procedural compositional grammar with its own silhouette, spatial logic, motion language, and shared-system visibility. | authored video, literal environment, color preset |
| **Field Forcing** | Typed continuous physical targets and idempotent Field Impulses offered to the Coupled Field. The Field Conductor derives them from Track Analysis; the Synesthesia Preview supplies only synthetic continuous targets. | shader settings, raw features, draw commands |
| **Field Impulse** | One confidence-gated, identity-bearing spatial cause that enters the Coupled Field once per Transport Epoch. It retains a presentation character so an admitted onset, rhythmic accent, Section boundary, and Source entrance can disturb the same world in visibly different ways. | generic pulse, scene cue |
| **Coupled Field** | Synesthesia's one bounded three-dimensional system of velocity, matter, pressure, charge, organization, and stable force poles. Every visible subsystem reads from or writes to this shared spatial state. | scene, tunnel, effect stack |
| **Field Frame** | An immutable CPU-side publication of current Field Forcing, accepted causes, stable force poles, transport context, and renderer diagnostics. High-volume particle and field buffers remain GPU-resident. | framebuffer, screenshot, scene state |
| **Transport Epoch** | A monotonic identity for one uninterrupted traversal of the Synesthesia musical timeline. A new Playback Entry or explicit Player seek starts a new epoch; ordinary playback does not. | timestamp, Playback Attempt, Track identity |
| **Back Sync** | Supported iPod-to-Host work associated with Sync, such as applying iPod ratings to Host media metadata or exporting iPod-only Tracks. | reverse sync, two-way Sync |
| **Export** | A user-directed copy of Tracks, playlists, or images from an iPod to the Host, independent of whether the item participates in the main Sync comparison. | Sync when no reconciliation occurs, extraction |
| **Commit** | The point at which a verified Storage Transaction becomes the accepted device state. | save, finish, write |
| **Rollback** | Recovery that restores the last accepted state after an incomplete or failed transaction. | undo, backup, retry |

## System boundaries

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Storage** | The generic subsystem responsible for safe Host filesystem and removable-media operations. | storage layer when physical capacity is meant, device service |
| **iPodDB** | The subsystem responsible for representing, parsing, validating, and serializing iPod database formats. | iTunesDB, database service, persistence layer |
| **Application Layer** | The iOpenPod subsystem that coordinates workflows and dependencies without owning GUI rendering. | core, backend, service layer |
| **GUI** | The Qt presentation boundary that displays state and delegates work to the Application Layer. | application, frontend logic, UI service |

## Relationships

- One **Physical Device** may expose one or more **Volumes**.
- One **Volume** may have one or more temporary **Mount Points**.
- One **Filesystem Session** belongs to exactly one **Volume** and one
  **Connection Generation**.
- iOpenPod has at most one **Active iPod**. Selecting another iPod ends the previous
  Filesystem Session.
- **Device Registry** resolves **Device Evidence** into an **Identification Result**,
  which may contain one exact **Device Profile** or bounded candidates.
- A **Device Profile** owns one set of **Device Capabilities**.
- Storage returns **Hardware Probe Observations**; the **Application Layer**
  translates them into **Device Evidence** and may perform **Device Metadata
  Reconciliation** only after the user selects an exact Device Candidate.
- **SysInfo Authority** records provenance for persisted metadata but remains device
  metadata; it is never promoted to current hardware evidence merely because its
  hashes still match.
- An **iPod Library** is represented by media files plus one or more databases such
  as **iTunesDB** and **ArtworkDB**.
- A **Podcast Subscription** groups the **Podcast Episodes** fetched for the current
  session or reconciled from the Active iPod's Tracks. Episode metadata is not part
  of the persisted subscription document, while **Listening History** remains
  independent of both membership and subscription lifetime.
- A **Sync** produces a **Sync Plan**, presents a **Sync Review**, and may execute one
  or more **Storage Transactions**.
- Starting the first entry in the **Playback Queue** removes it from that Queue and
  adds it to the top of **Playback History**. Both collections end with the
  application session and are cleared when the whole Library changes.
- The Application Layer's playback controller owns **Playback Queue**, **Playback
  History**, and transport policy. It gives the current Track's **Playback Source**
  to a **Playback Backend** and responds to the backend's position, state,
  completion, and failure events.
- An iPod **Playback Source** reads through the Active iPod's **Filesystem Session**.
  A changed Connection Generation or source identity ends playback rather than
  reusing stale access.
- A **Musical Analysis Job** observes a requested Track but remains
  independent of audio output and transport. It reads through a separate,
  identity-bound **Playback Source**, computes one fresh **Track Analysis**, and
  retains no Track-derived artifacts after that runtime result is released.
  While active, Synesthesia holds the current result and at most one prepared
  result for the next **Playback Entry**, which becomes current without reanalysis.
- A **Field Conductor** translates the current **Track Analysis** into
  **Field Forcing**. The **Coupled Field** applies those causes while its GPU
  projections publish diagnostics through a **Field Frame**.
- An explicit Player seek observed by Synesthesia starts a new **Transport Epoch**
  but does not rewind the **Coupled Field** or replay events skipped by the seek.
- The **Application Layer** coordinates **Device Registry**, **iPodDB**, and
  **Storage**; the **GUI** calls the Application Layer.

## Example dialogue

> **Developer:** "Storage found a new Mount Point. Is that enough to identify the
> iPod?"
>
> **Domain expert:** "No. Storage reports Device Identifiers and Volume Identity;
> Device Registry uses those identifiers to return a Device Profile."
>
> **Developer:** "Then iPodDB reads iTunesDB directly from the Mount Point?"
>
> **Domain expert:** "No. The Application Layer reads bytes through a Filesystem
> Session, gives those bytes to iPodDB, and later asks Storage to execute the reviewed
> Sync Plan as a Storage Transaction."

## Flagged ambiguities

- “iOpenPod” can mean the product, repository, distribution, or Application Layer.
  Use **iOpenPod** for the product and **Application Layer** for the architectural
  boundary.
- “device” can mean a generic **Physical Device**, a connected **iPod**, or a
  **Device Profile**. Name the intended concept.
- “model” can mean an iPod hardware model, domain data structure, or Qt item model.
  Prefer **Device Profile**, domain model, or Qt model respectively.
- “storage” can mean filesystem capacity or the **Storage** subsystem. Capitalize the
  subsystem name in prose.
- “database” can mean **iTunesDB**, **ArtworkDB**, or the **iPodDB** subsystem. Use the
  specific format or boundary name.
- “library” can mean the **Host Media Library** or **iPod Library**. Do not use it
  unqualified in synchronization discussions.
- Use **Device Registry** in prose and `device_registry` for its generic Python
  package. Branded packages retain **iOpenPod** and **iPodDB** where practical.
