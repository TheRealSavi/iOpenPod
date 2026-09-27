# Source Architecture

This document describes the high-level responsibilities and internal structure of the four primary source modules:

```text
src/
├── device_registry/
├── iOpenPod/
├── iPodDB/
└── storage/
```

Brief Summary:

- **Storage** knows about USB devices, volumes, filesystems, paths, safe device I/O,
  platform differences, transactions, and removable-media lifecycle.
- **Device Registry** identifies and describes supported iPod models and their
  hardware and software capabilities. It receives discovery evidence from Storage;
  it does not query host devices itself.
- **iPodDB** knows how to parse, model, and write iPod-specific database formats,
  including iTunesDB, ArtworkDB, and PhotosDB.
- **iOpenPod** is the application. Its Application Layer coordinates Device Registry,
  iPodDB, Storage, application state, and the GUI.

The four packages ship together as one iOpenPod application and one distribution.
They are separate to keep responsibilities and dependencies clear, not because they
are independently released products. Branded names retain their established
capitalization: iOpenPod, iPodDB, iTunesDB, ArtworkDB, and iPod. Generic Python
package and module names use lowercase conventions.

The Original iOpenPod is the behavioral and research baseline. iOpenPod 2.0 is built
incrementally until it reaches and then surpasses that behavior; there is no reduced
MVP that permanently narrows the target product.

---

## Device Registry

### Device Registry Purpose

Device Registry is the canonical source of knowledge about supported iPod models.

It answers questions such as:

- What model is this device?
- Which iPod generation does it belong to?
- What hardware capabilities does it have?
- Which database or artwork formats does it support?
- What screen resolution does it use?
- Which media formats can it play?
- Which firmware/device identifiers correspond to this model?
- Does this model require special handling?

Device Registry should focus on **device identity and capabilities**, not filesystem
operations.

It should not directly mount devices, manipulate files, write databases, or contain GUI code.

### Suggested Responsibilities

```text
device_registry/
├── registry
├── models
├── identifiers
├── capabilities
└── data
```

#### Registry

The registry provides the primary lookup API.

Example:

```python
result = registry.identify(evidence)
```

`DeviceEvidence` contains typed identifiers with provenance and evidence authority.
`IdentificationResult` is immutable and reports exact, ambiguous, conflicting,
recovery-mode, or unknown identification. It contains a Device Profile only for an
exact result; other recognized results expose bounded candidate profiles. The result
describes identity but does not authorize filesystem access or mutation.

Current Host hardware evidence outranks device metadata, which outranks derived
evidence. Equally authoritative exact identifiers that disagree must produce a
conflicting result rather than a guess. Product serials and USB or FireWire transport
serials remain distinct. A USB identifier is a Vendor ID and Product ID pair;
normal-mode identifiers are generally coarse constraints, and recovery-mode
identifiers never produce a normal exact result.

The built-in metadata adapters accept bytes or text already obtained by an
authorized caller. They do not accept paths or probe the Host. Storage and the
Application Layer gather and combine the evidence before asking the registry to
identify it.

The Registry boundary also owns a pure SysInfo reconciliation function. It accepts
ranked Device Evidence, one exact Device Profile, and already-read SysInfo,
SysInfoExtended, and iOpenPodSysInfoAuthority bytes. It returns desired bytes and a
change plan; it never accepts a path or performs I/O. The version-1 authority format
remains compatible with Original iOpenPod and adds explicit evidence-authority names
without treating persisted provenance as a new hardware observation.

#### Models

Defines immutable or mostly immutable device metadata objects.

Examples:

```python
DeviceProfile
DeviceIdentifier
DisplayCapabilities
AudioCapabilities
ArtworkCapabilities
DatabaseCapabilities
```

A device profile could contain information such as:

```text
model
generation
family
capacity
screen size
screen resolution
storage type
supported codecs
artwork formats
database format/version
special device flags
```

#### Identifiers

Contains logic and data for identifiers associated with iPod hardware.

Examples include:

- model numbers
- product identifiers
- USB vendor/product IDs
- serial-number families
- hardware strings
- firmware identifiers

The registry should normalize these identifiers before attempting lookup.

#### Capabilities

Defines reusable capability models instead of scattering model-specific booleans throughout the application.

For example:

```python
AudioCapabilities(
    supports_aac=True,
    supports_alac=True,
    supports_flac=False,
)

DisplayCapabilities(
    width=320,
    height=240,
    color=True,
)
```

This lets application code ask about capabilities instead of hard-coding individual models.

#### Data

Contains the actual device definitions.

This can be represented using:

- Python data structures
- JSON
- YAML
- TOML
- generated data

The rest of the application should access this information through the registry API rather than reading these files directly.

### Dependency Rules

Device Registry may depend on generic utility code, but should ideally not depend on:

```text
iOpenPod
iPodDB
GUI
Storage
```

USB and storage device discovery occurs in Storage. iOpenPod passes the resulting
identifiers to Device Registry, which answers:

> What known iPod profile matches these identifiers?

That produces a clean separation:

```text
Storage
    "A removable device appeared with these identifiers."

Device Registry
    "Those identifiers correspond to this iPod model."

iOpenPod
    "Open that device and construct the appropriate application state."
```

---

## `src/storage`

### Storage Purpose

`Storage` is the generic low-level subsystem responsible for safe interaction with host filesystem and removable storage.

It should not know anything about iPods, iTunesDB, artwork databases, tracks, playlists, or the GUI.

Its job is to provide a consistent abstraction over:

```text
Windows
macOS
Linux
```

and protect application code from dangerous direct filesystem operations.

### Core Responsibilities

`Storage` should own:

- removable-device discovery
- physical-device identity
- volume identity
- mount-point discovery
- filesystem capabilities
- root-bound filesystem sessions
- safe reads and writes
- atomic replacement
- copying and moving
- safe deletion/trash semantics
- storage transactions
- operation journals
- free-space checks
- disconnect detection
- safe eject/removal
- platform-specific storage APIs

A possible internal structure is:

```text
storage/
├── __init__.py
├── models.py
├── paths.py
├── errors.py
├── capabilities.py
├── session.py
├── filesystem.py
├── transaction.py
├── journal.py
└── platform/
    ├── base.py
    ├── windows.py
    ├── macos.py
    └── linux.py
```

### Models (Storage)

Defines generic storage concepts.

Examples:

```python
PhysicalDevice
DeviceId
Volume
VolumeId
MountedVolume
MountPoint
StorageCapabilities
HardwareProbeObservation
HardwareProbeResult
```

These should distinguish:

```text
physical device
    ↓
volume
    ↓
mount point
    ↓
filesystem session
```

A mount path such as:

```text
E:\
/Volumes/IPOD
/run/media/user/IPOD
```

must never be treated as the permanent identity of a device.

### Paths

Defines safe path abstractions.

For device-relative access, use a dedicated type such as:

```python
DevicePath
```

instead of passing arbitrary host `Path` objects through device APIs.

A `DevicePath` should:

- always be relative
- reject `..`
- reject absolute paths
- reject paths that escape the device root
- normalize separators
- avoid unsafe symlink/reparse traversal

Example:

```python
DevicePath("iPod_Control/iTunes/iTunesDB")
```

The application should not be able to accidentally pass:

```text
C:\Users\...
/home/...
../../...
```

to a device mutation API.

### Filesystem Sessions

A filesystem session represents authorized access to a specific mounted volume.

Example concept:

```python
DeviceFilesystemSession
```

It should be bound to:

```text
device identity
volume identity
mount point
connection generation
read/write capabilities
```

Once a device is disconnected, that session becomes permanently invalid.

A reconnect creates a new session.

This prevents a stale mount path from accidentally referring to another removable drive.

If the Active iPod disappears during an operation, Storage rejects further work for
that session and reports the loss to iOpenPod. iOpenPod stops the workflow and tells
the user that the operation may be incomplete. No software can finish verification
or guarantee rollback while the Volume is physically absent; recovery resumes only
after reconnection creates a new Connection Generation.

### Filesystem API

Application code should use controlled operations such as:

```python
fs.read(...)
fs.read_range(...)
fs.exists(...)
fs.stat(...)

fs.atomic_write(...)
fs.copy_from(...)
fs.move(...)
fs.trash(...)
```

Direct device-facing mutation calls such as these should be isolated inside Storage:

```python
Path.unlink()
os.remove()
shutil.rmtree()
Path.replace()
open(..., "wb")
```

This rule is primarily about authorized device roots. iOpenPod owns the meaning and
policy of ordinary application data such as settings, logs, caches, Backup
Snapshots, and temporary files. The narrow exception established by ADR-0014 is
global settings: Storage resolves the conventional Host configuration location and
atomically reads or replaces the file bytes, while iOpenPod owns its schema and JSON
encoding. Storage must not become a generic wrapper around every file iOpenPod uses.

The implemented foundation uses this public flow:

```text
Storage.discover() / Storage.inspect()
    ↓
MountedVolume
    ↓
Storage.open_session()
    ↓
FilesystemSession
    ↓
DevicePath operations
```

`Storage` is a deep module: platform selection, connection-generation tracking,
native identity reinspection, Host-side writer leases, containment checks, staging,
durability calls, and content verification remain behind those two public objects.
The only second adapter is `VirtualStoragePlatform`, which provides a real
filesystem-backed Volume for deterministic tests.

The initial `FilesystemSession` supports directory inspection, bounded reads,
fingerprints, create-only writes, fingerprint-checked replacement, explicit
Host/device copies, moves, recoverable trash and restore, free-space inspection, and
filesystem flushing. It intentionally exposes neither unconditional overwrite nor
permanent deletion.

Filesystem Sessions also expose native volume-label updates and custom-volume-icon
activation under the same writer lease and connection revalidation. These generic
operations apply filesystem constraints and verify the native result. The
Application Layer owns the name and icon policy; Storage knows nothing about the
Master Playlist or Device Profile.

### Transactions

Large or destructive operations should be planned and executed as transactions.

Typical lifecycle:

```text
ANALYZE
   ↓
PLAN
   ↓
VALIDATE
   ↓
EXECUTE
   ↓
VERIFY
   ↓
COMMIT
   ↓
CLEANUP
```

A transaction should support:

- dry-run
- validation
- progress reporting
- rollback where possible
- operation journaling
- interruption recovery

Deletion should generally occur after successful writes and verification.

Read-only transaction status distinguishes the recorded journal state from whether
its Physical Device and Volume identities match the current session. A valid
committed or restored journal with an outdated Host identity does not imply an
interrupted operation. It remains untouched without offering cleanup. Recovery and
cleanup still require exact identity validation; malformed or nonterminal journals
continue to block selection for recovery attention. See ADR-0089.

A Backup Snapshot is not a transaction phase for another feature. The implemented
backup and restore workflow is standalone and is not invoked by Sync, Library save,
or any other device workflow. Those workflows retain their own Storage validation,
verification, and recovery requirements.

`BackupRepository` owns Backup Archive format v4, which continues the Original
iOpenPod v2 and v3 format sequence. Its manifests use
exact Device Path components, immutable content identities, serial-first Backup
Identifiers, checksummed catalogs, and a shared content-addressed object store. A
product serial is preferred, a transport serial is used when no product serial is
known, and hashed Volume Identity is retained as the best-effort fallback. When both
sides know a serial, only a serial match associates them; otherwise the Volume
fallback is used. Raw serials, Original archive device keys, and Host volume
identifiers are not persisted in v4 manifests or directory names.
The separate Legacy Backup Import reads and validates Original iOpenPod version-2 and
version-3 manifests and blobs, then publishes v4 snapshots without modifying the
source archive. When an Original archive key matches one of the Active iPod's current
product- or transport-serial claims, import assigns that snapshot the complete native
Backup Identifier and Archive Key while retaining hashed Original-source provenance.
This also lets a repeated import consolidate snapshots previously converted into a
separate legacy archive. Unmatched imports retain their legacy identity and restore
confirmation rules, and explicitly unstable imports are never promoted. Every
converted Original snapshot is classified as Import rather than inheriting the
Original capture reason; retained `legacy_source` provenance gives already-converted
catalogs the same classification. Invalid catalogs remain visible for diagnosis but
fail closed for
export, deletion, restore, retention, and object collection. Every archive read or
mutation holds a Host-side cross-process repository lease, and interrupted capture is
reconciled without publishing or collecting unreferenced content.

`BackupService` is the device-orchestration seam. Snapshot capture and restore receive
only an identity-bound Filesystem Session from `DeviceCoordinator`; the repository
never receives a Mount Point. Capture streams and hashes each new or changed file once,
verifies the staged Host object, and ends with a metadata-only tree rescan. Ordinary
captures reuse a latest-snapshot object when its path, size, modified time, and safe
Host shape still match; forced restore-safety captures copy every file. Restore and
export perform deep object verification before consuming a snapshot. This avoids an
unbounded second Device read while retaining full SHA-256 content identities. Restore
requires the selected archive's serial-first Backup Identifier to match the Active
iPod, using its Volume fallback when either side has no serial. It verifies all needed
blobs, creates a forced pre-restore safety checkpoint, performs fingerprint-checked
writes and recoverable removals through
Storage as one bounded transaction, verifies every restored hash and modification
time, and flushes the Volume. Its durable Operation Journal refers to the forced Host
safety snapshot for recovery bytes and stages at most one replacement file on-device.
Cancellation is available only until device mutation begins. An unresolved restore
pins its safety checkpoint, appears as a persistent Restore Recovery action, and
blocks further restore mutations. Recovery verifies and finalizes an already
committed target or restores and verifies the safety snapshot; it never guesses from
the Host record alone. Unpinned automatic pre-restore safety checkpoints remain
outside normal retention and are bounded to the newest five.

`BackupController` serializes long-running archive work outside the GUI thread. The
Backups page renders immutable inventory and catalog projections and sends user
intents back to that controller; it never reads archive manifests or device paths.
Typed terminal outcomes distinguish cancellation, pre-mutation failure, incomplete
publication, durability pending, a verified already-current no-write result, and
verified completion, and carry actionable recovery guidance to the GUI.
Export materializes a snapshot beneath a new uniquely named Host folder and never
overwrites existing user files. See ADR-0039, ADR-0040, and ADR-0062.

`FilesystemSession` now accepts immutable `StorageTransaction` plans with ordered
writes, recoverable removals, and unchanged file dependencies. Read-only validation
checks expected file fingerprints and staging/recovery capacity. Execution holds
one Volume writer lease, streams Host files through bounded buffers, retains
replaced originals, and verifies every staged file before publishing any target.
Writes are individually atomic; the whole transaction is not an instantaneous
filesystem-wide swap. Removals follow verification of all writes.

Versioned Operation Journals retain intent and distinguish staging, prepared,
publishing, committed, restoring, and restored states. `inspect_transaction` captures
the journal and every target/dependency fingerprint. `restore_transaction` rechecks
that exact observation, every required original, and available restoration space
before changing any target. A later unrelated edit blocks the entire restoration.
Recovery can resume with a new Filesystem Session after reconnecting to the same
Physical Device and Volume. Generic transaction recovery content remains retained,
and rolling an interrupted publication forward is not implemented. Backup restore is
the explicit exception: after it verifies either the selected target or the Host
safety snapshot, it finalizes only that exact terminal transaction namespace. See
ADR-0029 and ADR-0039.

The application now captures artwork inventories/prefixes and removed-media
dependencies, and privately binds their Storage Transaction to the exact issued
Library Review. It publishes thumbnail files, ArtworkDB, PhotosDB, iTunesDB, then obsolete
media removals. Shared media remains; newly pending positional sidecars block
structural changes. Review file descriptions are read-only information. See ADR-0030.
Incoming-media transaction composition and general Sync remain unfinished. iOpenPod must
not reproduce these transactions with raw filesystem mutations outside Storage.

### Platform Backends

#### Windows

The Windows backend handles:

- physical disk/device identity
- volume GUIDs
- drive-letter/mount-point resolution
- USB/removable-device lifecycle
- safe removal by matching the retained physical disk number to a present disk
  device interface and calling Configuration Manager
- filesystem capability inspection

Drive letters should be treated as temporary mount locations, not persistent device identity.

#### macOS

The macOS backend should handle:

- mounted volumes
- BSD whole-disk to USB hardware correlation through IOKit
- Disk Arbitration integration
- mount/unmount lifecycle
- device disappearance
- eject
- filesystem information

#### Linux

The Linux backend should preferably integrate with desktop storage infrastructure such as UDisks2 rather than assuming fixed mount paths.

It should handle:

- drive/block/partition/filesystem relationships
- mount points
- disconnect events
- eject/power-off behavior
- filesystem capabilities

The initial adapter reads the kernel mount table and non-privileged udev properties,
so it does not assume a desktop-specific mount directory. UDisks2 lifecycle events
remain the preferred next integration for event-driven discovery. User-directed
eject already resolves the selected block object through UDisks2, unmounts every
mounted filesystem on its Drive without force, and requires confirmed Drive power-off.

All native safe-removal paths revalidate the retained Connection Generation before
calling the Host. Windows preserves Plug and Play veto details; macOS separately
checks whole-disk unmount and eject; Linux preserves UDisks2 busy and authorization
errors. A refusal before unmount keeps the generation available for a re-opened
read-only session. An unmounted-but-unconfirmed partial result expires it. See
ADR-0060.

All three native adapters implement the same generic SCSI VPD probe seam. Windows
uses SCSI pass-through against the selected Volume, macOS uses an IOKit SCSITask
anchored by current USB identifiers, and Linux uses SG_IO when permissions allow and
always exposes non-privileged udev properties. Storage returns standard inquiry
identity, page-0x80 unit serial, concatenated vendor data-page bytes, and opaque Host
properties. It neither parses an iPod plist nor assigns product-serial semantics.

Linux packages also ship an Application-owned, least-privilege udev rule. The rule
asks root-time `scsi_id` to read only VPD page 0x80 and publishes the result as an
opaque property; it does not grant raw-disk access. The Application Layer recognizes
that property for an Apple iPod and asks the user to install or refresh the rule when
needed.

### Dependency Rules (Storage)

`Storage` should not import:

```text
device_registry
iPodDB
iOpenPod
```

It is deliberately generic.

A useful test is:

> Could `Storage` safely manipulate an ordinary USB flash drive without knowing what an iPod is?

The answer should be yes.

---

## `src/iPodDB`

### Purpose (iPodDB)

`iPodDB` contains the iPod-specific database and binary-format layer.

It knows how to:

- parse iPod database bytes or streams
- represent their structures in Python
- validate records
- serialize records
- write compatible binary output
- translate database records into the common immutable Library contract

It should not contain application GUI logic.

iPodDB does not use Storage and does not know about iOpenPod. It accepts bytes or
generic binary streams and returns structured database data or serialized bytes.
iOpenPod decides when to read or persist those bytes through Storage.

### Common Library interface

`iPodDB.library` provides the source-independent `LibrarySnapshot`, Track, Playlist,
and optional `PhotoLibrary` records. They are ordinary frozen dataclasses with
semantic enums, boolean flags, and explicit units. Other Library Sources can
construct the same records without database documents or Qt objects. Optional
source-specific detail records preserve diagnostics without weakening the common
contract.

`IPodLibrary` is the iPod source adapter. It parses caller-supplied iTunesDB or
iTunesCDB bytes, translates the known metadata, links artwork, and privately retains
the lossless documents and physical source artifacts. iTunesCDB is the sole Library
read authority on late devices; firmware-facing SQLite artifacts are never merged
back into the semantic snapshot.
The adapter's `snapshot` is the only library data published in Active iPod state;
the adapter itself stays in the private device connection. `artwork_read` and
`photo_read` return typed relative byte-range plans and decoders for caller-supplied
bytes. The Application Layer supplies Device Registry capabilities and performs
validated Storage reads. The source adapter knows neither dependency.

Application and GUI consumers import the public contract, never the binary-format
packages. Snapshot construction and edits do not change the retained databases.
Source-bound Library Drafts now provide semantic preparation over the existing
lossless writer path. Analysis returns changes and required resources; preparation
reconciles retained records and verifies finalized output without filesystem I/O.
The Application Layer exposes background Review Changes with revision checks,
grouped diagnostics, and cancellation. Physical Sync remains separate. See
[Library contract](library-contract.md), [Library writing](library-writing.md),
ADR-0019, and ADR-0021.

### Lossless round-trip requirement

Unknown Data is expected in real iPod databases. If a database is parsed and then
serialized without an application edit, the output must reproduce the original
bytes exactly. This includes unknown fields, unknown Chunks, flags, ordering,
padding, and any other retained bytes.

iPodDB therefore preserves the original encoding needed for lossless serialization
alongside the values it understands. Merely encountering Unknown Data is not a parse
error and must not cause normalization or cleanup. Structurally malformed or
truncated data is a separate condition and may produce a typed parse error.

Each database family's shared Chunk Definitions are the single source of truth for
known fields. A `ChunkDefinition[HeaderType]` owns its Header Marker, purpose,
versioned header sizes, extent convention, body kind, ordered child groups, field
offsets, binary data types, sizes, defaults, requirements, and converters. Every
known Chunk must have a complete definition. Each family has exactly one
`DatabaseDefinition[RootHeaderType]` that aggregates the root Chunk, all known Chunk
Definitions, and all MHSD dataset definitions for both parsing and writing. Parser
definitions add MHOD decoding behavior without creating a second structural
registry, header map, policy flag, or compatibility path.

The shared reader follows one definition-driven structural path for iTunesDB,
ArtworkDB, and PhotosDB. Unregistered Header Markers follow one explicit Unknown Data path: a
structurally valid, length-delimited opaque Chunk. The shared writer owns the inverse
recursive structure, including validation and length and child-count repair. Format
writers vary only where their MHOD payload encodings genuinely differ. Shared binary
structure machinery owns field reflection, parsing, writing, retained-short-header
behavior, and exact floating-point retention so reader and writer implementations do
not depend on each other. Parsed Chunks retain their raw header, body, original
decoded payload references, and source suffix so centralization does not weaken
lossless round trips.

iTunesCDB is framing around that single iTunesDB path, not a second Chunk parser:
the root header remains physical, the child extent is one bounded zlib stream, and
the framing is restored before physical signing. `iPodDB.SQLiteDB` owns generation
and validation of the five late-iPod SQLite projections and the Locations checksum
book from a checked Library Snapshot. Its Interface accepts semantic data and returns
artifact names with bytes; it knows neither device paths nor persistence. Device
Registry chooses required artifacts and per-artifact checksums. iOpenPod maps those
artifacts to device-relative paths and publishes them through Storage, but never
loads them as Library input.

Each public parser returns a `DatabaseDocument[RootHeaderType]`, which is the parsed
root `ParsedChunk` rather than a wrapper or a second writer model. A consumer finds a
`ChunkSelection[RootHeaderType, SelectedHeaderType]`, applies an immutable typed
header, prefix, payload, or child edit, and replaces that selection in the Database
Document. The matching writer accepts that same document type directly. Selections
remain anchored to the root even when found within another selection, so callers do
not recursively rebuild ancestors. A selection becomes stale after its selected
branch is replaced and must then be reacquired explicitly.

Every understood MHOD payload representation has one corresponding inverse encoder.
An unchanged representation uses retained source bytes; an edited representation
must pass its registered typed encoder. Context-dependent MHOD meanings are resolved
and validated before unchanged-byte preservation, so moving a Chunk cannot bypass
its new parent contract. Writers own derived binary values such as extents, child
counts, string lengths, and payload entry counts.

Suggested structure:

```text
iPodDB/
├── library/
│   ├── models.py
│   ├── database.py
│   ├── artwork.py
│   ├── photos.py
│   ├── _photo_projection.py
│   ├── _photo_analysis.py
│   ├── _photo_writing.py
│   └── _projection.py
├── Shared/
├── ArtworkDB/
│   ├── Builder/
│   ├── ithmb.py
│   ├── Parser/
│   ├── Shared/
│   └── Writer/
├── PhotosDB/
│   ├── Builder/
│   ├── Parser/
│   ├── Shared/
│   └── Writer/
└── iTunesDB/
    ├── Builder/
    ├── Parser/
    ├── Shared/
    └── Writer/
```

---

### `iPodDB/Shared`

Contains code shared between multiple iPod database formats.

This may include:

- binary readers
- binary writers
- endian helpers
- string encoding utilities
- binary field definitions
- common record types
- validation helpers
- common exceptions
- shared constants
- generic parser utilities

Examples:

```python
BinaryReader
BinaryWriter
RecordHeader
ParseError
WriteError
ValidationError
```

This layer should remain database-format-oriented rather than application-oriented.

---

### `iPodDB/ArtworkDB`

Contains support for iPod artwork-related databases and associated structures.

```text
ArtworkDB/
├── Builder/
├── Parser/
├── Shared/
├── Writer/
└── ithmb.py
```

#### `ArtworkDB/Shared`

Contains common artwork database definitions shared by parsing and writing.

Potential contents:

- artwork record models
- image format descriptors
- pixel-format definitions
- artwork IDs
- image dimensions
- thumbnail metadata
- database constants
- record tags
- format/version definitions

The parser and writer should both depend on these shared structures.

Example conceptual models:

```python
ArtworkDatabase
ArtworkRecord
ArtworkFormat
ArtworkImage
ThumbnailRecord
```

The shared package should contain **representation**, not I/O orchestration.

The immutable Artwork Index is an internal source projection over the lossless
Database Document. It resolves image and Track database IDs to format IDs and exact
iTHMB byte ranges in constant time. The adjacent iTHMB decoder consumes one
already-bounded byte payload plus an explicit layout and returns owned RGB pixels.
Neither component accepts a path, reads a filesystem, selects a Device Profile, or
constructs a Qt object.

#### `ArtworkDB/Parser`

Responsible only for turning artwork database bytes or streams into structured
Python objects.

Conceptually:

```text
bytes
  ↓
ArtworkDB Parser
  ↓
ArtworkDatabase
```

Responsibilities include:

- reading headers
- decoding record structures
- validating lengths
- handling database versions
- resolving references
- reporting malformed data
- preserving unknown fields and Chunks exactly

The parser has no device file access.

Its output should be reusable independently of the GUI.

Example:

```python
database = ArtworkDBParser.parse(data)
```

or:

```python
database = ArtworkDBParser.parse_stream(stream)
```

#### `ArtworkDB/Builder`

Responsible for constructing new writable Chunks and Database Documents through the
same registered definitions used by the parser and writer. Construction does not
belong in a writer module. iTunesDB follows the same Builder/Parser/Shared/Writer
package pattern.

Known Device Profiles supply the first ArtworkDB's creation policy through the
Application Layer's write target. iPodDB creates the standard datasets and declared
cover representations without existing artwork files, while retained documents
keep their original variants and Unknown Data. Older Track layouts use reverse
ArtworkDB links. Persistence still uses the reviewed Storage Transaction. See
[ADR-0033](adr/0033-create-artworkdb-from-catalog-capabilities.md).

#### `ArtworkDB/Writer`

Responsible for serializing structured artwork data back into the iPod format.

Conceptually:

```text
ArtworkDatabase
      ↓
ArtworkDB Writer
      ↓
bytes
```

Responsibilities include:

- calculating offsets
- calculating record sizes
- encoding fields
- writing headers
- generating compatible binary output
- validating output before commit

The writer should produce bytes or write to a generic binary stream.

Actual safe persistence to a device belongs to Storage under iOpenPod coordination.

Example:

```python
data = ArtworkDBWriter.serialize(database)
```

iOpenPod can then give those bytes to Storage as part of a reviewed Storage
Transaction. This keeps the format writer independent from host filesystem details.

---

### `iPodDB/PhotosDB`

Contains the lossless parser, writer, builder, and definitions for the on-device
`Photos/Photo Database` artifact.

```text
PhotosDB/
├── Builder/
├── Parser/
├── Shared/
└── Writer/
```

PhotosDB uses the same evidenced nested MHFD-family Chunk and MHOD layouts as
ArtworkDB, so shared Header and payload representations remain one source of binary
field knowledge. PhotosDB owns a distinct root Header type, Database Definition,
Chunk-definition graph, parser context, and public parser/writer seam. This keeps
the two artifact types statically and dynamically distinct without duplicating all
known field offsets.

The parser and writer accept and return data only. The common Library adapter
projects PhotosDB into immutable semantic Photo records and reconciles its supported
draft edits over the retained document. Device Profile format selection, iTHMB or
full-resolution image I/O, allocation, and safe publication remain Application
Layer and Storage concerns. See ADR-0052 and ADR-0053.

---

## `src/iOpenPod`

### Purpose (iOpenPod)

`iOpenPod` is the main application.

It is distributed as one application. Device Registry, iPodDB, and Storage are
internal packages with enforced dependency direction, not separately installed or
versioned products.

It owns:

- application startup
- application state
- user-facing workflows
- domain services
- Qt models
- GUI composition
- theming
- internationalization
- application assets

### Active iPod and Sync behavior

Storage may discover several connected iPods, but the GUI presents them through the
Device Picker and the user selects one Active iPod. iOpenPod loads and operates on at
most one Active iPod at a time. Selecting a different iPod cancels safe-to-cancel
work, invalidates the previous Filesystem Session, clears device-scoped state, and
opens a new session for the selected iPod.

After selection succeeds, the Application Layer stores the selected Volume Identity
in global settings. When a later discovery finds no Active iPod, it automatically
runs the ordinary selection workflow only if exactly one ready Device Candidate has
that Volume Identity. Device Candidate IDs remain scoped to a Connection Generation
and are never persisted. A missing, unready, or duplicate match leaves no Active
iPod; there is no visible setting for this restoration behavior.

Sync is primarily Host-to-iPod. It compares a Host Media Library with the Active
iPod's iPod Library, presents a Sync Review, and applies the selected additions,
removals, conversions, metadata updates, and artwork changes. Supported iPod-to-Host
behavior includes Back Sync of ratings and related metadata, exporting iPod-only
Tracks, and exporting images. These reverse-direction operations do not make Sync a
general two-way conflict-free replication system.

The implemented pre-Sync entry point begins with Host Media Scan. Sync with Host
first opens a modal media-folder dialog. Accepting it persists the staged choices,
starts one background scan of the selected folders, and opens the full-window Sync
Workspace for progress, selection, and Review. The scanner covers the enabled audio,
video, Photo, and Playlist types and enumerates a
canonical file catalog before reading metadata, reuses a checksummed application
cache entry only when path, media kind, size, and modification time still match, and
then repeats the metadata-only enumeration. New or changed audio and video files also
receive a cancellable, bounded raw Chromaprint algorithm-2 fingerprint from `fpcalc`;
new and changed files are inspected by a bounded pool of at most eight workers so
independent metadata reads and fingerprint processes can overlap without moving
progress publication, cache mutation, or final validation off the owning scan worker;
the fingerprint is retained in the Host source adapter and its versioned cache for
later Sync matching. A changed catalog becomes a scan diagnostic and the best-effort
snapshot remains available for Review; Sync execution revalidates current source
facts before any device write. This preserves the metadata-first reuse pattern
without making cloud-backed folders fail on ordinary source churn. The cache is not
source authority. See ADR-0082.

Optional acoustic analysis does not gate explicit incoming Adds. Previously proven
Sync paths match before missing acoustic evidence is classified. Helper v3 permits
an empty fingerprint only alongside committed Sync Details and continues reading
v1 and v2. Converted Photos retain separate Host and iPod content digests; oversized
image containers are streamed into bounded PNG stills (ADR-0086).
FFmpeg/FFprobe preflight applies only to incoming Tracks; fpcalc is a matching
aid. Storage's explicit best-effort Host enumeration retains independent readable
entries while checking directory identity. Inspection progress follows completion
order, and preparation reports reading, inspecting, converting, and verifying.
Artwork extraction streams the enclosing media, and FFprobe diagnostics alone do
not reject successful structured output. See ADR-0084.

Media preparation respects Host-native path spelling, selects a marked-default or
first-probe-order motion-video and audio stream when a container carries multiple
choices, and scopes FFmpeg options to the selected encoder. Removing extra streams
forces a prepared output and reports the selected streams as warnings. See ADR-0083.

Storage owns Host directory enumeration, file observations, and read-only stream
lifetimes for metadata, Photos, and artwork. Media parsers receive seekable streams
or captured bytes instead of filenames. Storage pins the observed file and its path
components, checks for replacement or modification, and closes streams on failure
or cancellation. This permits metadata inspection without copying every selected
media file or loading it entirely into memory. Storage also launches fingerprint
processes against validated inputs and owns temporary device-scan captures.

The Host Library Source projects scanned Tracks, Photos, and Playlists into the same
immutable `iPodDB.library.LibrarySnapshot` records used by the iPod source. Absolute
Host access paths remain in source-specific `HostMediaSource` records or descriptive
common locations; they do not grant device access. Playlist references outside the
selected media catalog (including excluded media types and subfolders) pause the
worker at a review dialog. Available entries can be accepted
or denied individually or in bulk. Only accepted supported files are inspected and
made available to Playlist membership. M3U/M3U8, PLS, XSPF, WPL, and ASX/WAX/WVX
parsing consumes bounded Storage reads. Storage rejects unsafe local path syntax,
links, reparse points, special files, and indirect Windows network drives. Approved
external audio/video files are inspected through private Storage captures tied to
the reviewed file identity. Approval never recurses into another Playlist or carries
over through the cache to a later scan. See ADR-0074. Track inspection prefers bounded embedded
artwork and otherwise records a deterministic common folder-level cover for lazy,
source-validated Host presentation. The Sync Workspace shows scan progress and, on
completion, presents a dedicated, read-only Host browser. It is made from the same
page and model classes as the iPod browser but is
not a source choice in the normal sidebar. Its Library Workspace, Playlist tree,
Track models, and Photo loader are source-isolated, so the Active iPod Library Draft
remains loaded. Host Photo reads
run through the shared asynchronous, byte-bounded presentation pipeline and reject a
file whose observed size or modification time changed after the scan. See ADR-0063
and ADR-0064 through ADR-0067.

In Select Media, the shared Album and collection pages use a full-page detail mode.
An ordinary card click opens artwork, metadata, bulk Sync Selection actions, and the
existing Track table with standalone search. The browser has no lower Track pane or
vertical splitter. Back retains the browser instance and its query, sort, grouping,
view mode, and position. Card checkbox and modified selection gestures remain in the
browser, and selection regrouping does not change an open detail page. See ADR-0072.

The global iPod Library View Mode setting defaults to Split Table. Whole Page Table
uses that same detail page for iPod Albums, Artists, Genres, TV Shows, and Music
Videos, including Albums opened from Artist and Genre list views. Layout changes
reuse the existing browser and Track table, preserving their models and iPod
actions. Sync Selection controls remain exclusive to Select Media, whose layout
does not follow this setting. The choice is persisted through the global settings
service and applies immediately.

When an Active iPod is available, the pre-Sync workflow then runs an iPod Media Scan.
The Application Layer loads the versioned, checksummed
`iPod_Control/iOpenPod/library-sync-helper.json` through the Active connection and
indexes it by persistent database Track ID and Photo ID. An entry is reusable only
while its Device Path, size, and filesystem-aware modification time still match.
Only missing or stale Track entries are copied through Storage to verified temporary
Host snapshots for bounded Chromaprint calculation. Full-resolution Photo files use
Storage-calculated SHA-256 fingerprints; Photos with only packed iTHMB
representations report that exact correlation is unavailable.

The helper retains optional Sync Details—last successful Sync time, Host path hint,
Host size and modification time, source and device formats, and conversion status.
Scanning existing media never invents those facts. The current Library database is
fingerprint-checked before helper publication, and publication uses an atomic,
generation-checked Storage write. Invalid helpers remain untouched for explicit
recovery. Read-only devices can still be scanned for the current run but cannot cache
the new evidence. Host Photo records carry matching SHA-256 evidence in Host Media
Scan cache format v5. Neither cache is part of the common Library Snapshot or grants
permission to mutate a device. See ADR-0065.

After both scans complete, the Application Layer prepares one immutable Sync Plan.
It first uses the proven Host path hints in Sync Details so changed content remains
associated with the iPod item produced by the previous successful Sync. Remaining
Tracks correlate through unique Acoustic Fingerprints; remaining full-resolution
Photos correlate through unique Image Content Fingerprints. Missing, conflicting,
or non-unique evidence produces Needs attention rather than a guessed action.

Host-only items are Add, and iPod-only items are Remove. For a correlated item with
Sync Details, the current Host size and modification time are compared with the Host
facts recorded by that successful Sync. Either difference produces Update; matching
facts produce In sync. A unique content match without Sync Details is also In sync
for the current comparison without inventing provenance. A mutable Sync Selection
then captures desired iPod membership without changing the comparison or Host Library
Snapshot. Correlated Host items start selected, Host-only items start unselected, and
iPod-only removal candidates start unchecked in Review. The final selected Sync Plan
is presented in collapsible Track and Photo action groups with virtualized detail
tables, search, and action/media filters. Final Review exclusions belong to Sync
Selection and skip actions without changing desired Host membership. Group
checkboxes select matching items, while Select All and Select None apply across
filters. Needs attention and In sync remain non-actionable. Changing the Active
iPod clears the comparison. Sync Selected reserves the clean Library Workspace,
captures transcoder and Sync settings, revalidates the selected plan and source
facts, and prepares media concurrently on the Host. Independent preparation
failures retain existing device media while other selected changes may proceed.
An isolated Library Draft carries successful media, Photo, artwork, and Playlist
changes into the existing issued Library Review and ordered Storage Transaction.
The Library Sync Helper is updated only after verified publication. Device writes
remain sequential; the USB bus is not used for parallel transcoding. See ADR-0066,
ADR-0067, ADR-0070, and ADR-0076.

The result page exposes item diagnostics, safe cancellation, Restore Previous
Library, Retry Cleanup, and Keep Current Contents. Pending recovery survives
restarts in device journals, with no Host setting. Discovery lists affected iPods
without preventing selection of other devices. Selecting an affected iPod requires
a restore-or-keep choice before metadata repair or Library loading. Recovery can
restore an unreadable Library through a freshly validated Storage session. Keeping
current contents retires the journal through Storage after explicit confirmation,
retains recovery copies, and reloads without metadata repair. An unreadable current
Library is reported separately from recovery. Cleanup accepts only terminal
transactions and preserves current contents. See ADR-0089.

Track membership changes capture positional playback sidecars as transaction
dependencies or replacement writes. iPodDB remaps Play Counts rows and On-The-Go
indexes from original to desired Track order while retaining opaque record and
header bytes. Appended Tracks need no invented history. Sidecar edits or new files
after capture stop publication, and recovery restores sidecars with the Library.
History remains in its sidecar; it is not applied twice or discarded. See ADR-0085.

Select Media and Review share a storage bar above their content. It combines the
Active iPod's last observed Volume capacity with the selected Sync Plan and captured
media file sizes; changing a selection performs no filesystem I/O. Incoming media
currently uses Host source sizes because transcoder output estimates are not yet
available. Removals and replaced files use scanned iPod sizes, and shared files are
credited only once after their last scanned reference is removed. The bar explicitly
labels this a source-size estimate, identifies unresolved items excluded from the
projection, and reports provisional over-capacity values.
Artwork, packed Photo representations, database growth, and temporary transaction
space are not estimated. This preview is not a capacity validation or a guarantee
that Sync execution will fit. Storage validates actual prepared transaction space
before publication. Changing the Active iPod clears the estimate.

Long-running discovery, parsing, comparison, transcoding, copying, backup, and Sync
work must not block the GUI thread. iOpenPod owns progress, safe cancellation, and
stale-result rejection. Low-level work must expose enough state for iOpenPod to stop
at a safe point rather than killing a write arbitrarily.

Backup capture reserves the current Active iPod against connection changes and
Application Layer device writes without marking all device activity busy. Its
read-only Backup Session retains the identity-bound Filesystem Session but not the
Device Coordinator state lock, so browsing, artwork, Host export, Library
preparation, and playback range reads can continue. Restore and Restore Recovery
remain exclusive. See ADR-0041.

Suggested structure:

```text
iOpenPod/
├── app/
│   ├── device_controller.py
│   ├── photo_controller.py
│   ├── playback_controller.py
│   ├── core/
│   ├── models/
│   ├── playback/
│   └── services/
│
├── assets/
│   ├── fonts/
│   ├── glyphs/
│   └── images/
│
└── GUI/
    ├── delegates/
    ├── dialogs/
    ├── pages/
    ├── widgets/
    └── presentation/
        ├── i18n/
        └── theme/
```

---

### `iOpenPod/app`

Contains the non-visual application layer.

```text
app/
├── core/
├── models/
├── playback/
├── podcasts/
└── services/
```

#### `app/core`

Contains foundational application infrastructure.

Potential contents:

- application bootstrap
- application context
- configuration
- settings
- logging
- dependency wiring
- application paths
- global enums
- shared application exceptions
- task/executor setup

Application infrastructure chooses policy for settings, logs, caches, Backup
Snapshots, and temporary files according to the standard conventions of Windows,
macOS, and Linux. Global settings use Storage's generic Host configuration-file
boundary for platform path resolution and atomic byte replacement. They are not
device-facing operations and do not use a Filesystem Session. Other application
file categories remain separate decisions.

`ApplicationStatus` is the process-wide seam for short user-visible status text.
Callers set the default message or publish and clear source-owned messages without
knowing about windows or widgets. It exposes immutable active-message snapshots in
arrival order and rotates the visible message every four seconds when several
sources are active. New sources appear immediately; updates to existing sources
preserve the rotation position and cadence. Clearing or expiring the visible source
advances to the next remaining source, and the default returns when none remain.
`MainWindow` adapts the resolved message to the shared `QStatusBar`. Its small corner
button opens a live, scrollable list of all active messages, excluding the default;
closing that list does not clear messages. It also adapts typed Backup progress
to a permanent progress indicator there, so an active operation remains visible when
the user navigates away from the Backups page. Pages do not create local status strips
or receive a status-bar widget.

Examples:

```python
AppContext
AppSettings
ApplicationPaths
ApplicationStatus
```

This is where the application's major services and models can be constructed and wired together.

Example dependency composition:

```text
Storage
DeviceRegistry
DeviceCoordinator
DeviceController
IPodLibrary
SyncService
PlaybackController
PlaybackBackend
Qt Models
ThemeManager
I18nManager
       ↓
   AppContext
```

The GUI can receive this application context or selected dependencies rather than importing global singletons.

#### `app/models`

Contains application-facing models.

These may include:

- Qt item models
- application state models
- view-facing models
- queue models
- device models
- track models
- album models
- playlist models
- sync-plan models

Examples:

```python
TrackModel
AlbumModel
PlaylistModel
DeviceCandidate
DeviceDiscovery
ActiveIPod
LibrarySnapshot
SyncPlanModel
```

For Qt views, this is where implementations such as these belong:

```python
QAbstractListModel
QAbstractTableModel
QAbstractItemModel
QSortFilterProxyModel
```

Models should expose data and state.

`LibraryWorkspace` owns metadata, device-name, Playlist, Photo, artwork,
song-addition, and Track-removal drafts, supported Smart Playlist matching, and
atomic application of changed rules with their saved entries. The source-neutral
Playlist contract remains in `iPodDB.library`, where
the iPod adapter projects dataset selection, master naming, hierarchy, and smart
conditions. `PlaylistTreeModel` presents the hierarchy and validates scoped drag
data; GUI pages send editing intents to the workspace. Neither path edits retained
Database Documents or persists device files. The global Draft all changes setting
defaults to off. `LibraryWriteController` automatically prepares and accepts the
current draft after edit observers finish; enabling the setting retains manual
Review Changes and Save to iPod. The sidebar hides Review Changes while off.
Both modes use `DeviceCoordinator` for background preparation and a verified,
recoverable file transaction through Storage. Failed attempts retain the draft,
open diagnostics, and wait for correction or an explicit retry. See ADR-0073.
The exact issued review binds captured resources and dependencies to song,
thumbnail, ArtworkDB, PhotosDB,
iTunesDB/iTunesCDB, and SQLite companion publication followed by obsolete-media
removal. `MusicImporter` inspects compatible
audio and embedded covers from one Storage-captured Host snapshot. It supplies
semantic Tracks and source content evidence; `iPodDB.library.media` owns native
codec mapping. `MusicImportController` applies a complete inspected batch only to
its captured workspace revision and Active iPod. Music import remains an
Application Layer capability with no GUI entry point, file picker, or progress
dialog. Imported drafts follow the same automatic or manual save policy.
Source paths are streamed again at save and must match the captured content hash
before publication. No conversion or Sync engine is involved. See ADR-0026,
ADR-0030, ADR-0031, and ADR-0032.
The controller captures one immutable Library Preparation Request with desired
state, source, and workspace revisions. Request/result contracts live independently
of Qt in `iOpenPod.app.library_write`. Entered writer stages support progress and
cooperative cancellation. Read-only inspection reports expose captured changes,
resource evidence, output hashes, and diagnostics; they cannot replay a write or
restore a saveable stale result. See ADR-0023 and `docs/library-writing.md`.

They should not perform arbitrary filesystem writes or contain widget logic.

Large-library models should support at least 10,000 Tracks without creating one
Python or QWidget presentation object per visible cell. Prefer immutable snapshots,
stable identifiers, cached normalized search values, derived aggregate models, and
proxy models over page-local copies. A whole-snapshot replacement should use one
model reset. Incremental workflows should emit proportionate model signals and
restore selection through stable identifiers rather than rebuilding widgets.

Views should be able to display the natural source order without an eager startup
sort. Expensive filtering, sorting, or aggregation must be measured at the target
library size, and long-running parsing or service work remains outside the GUI
thread.

#### `app/podcasts`

Contains the device-aware Podcast Catalog and its external adapters. It exposes one
immutable Podcast Snapshot composed from explicit Podcast Subscriptions, refreshed
RSS/Atom metadata, independent Listening History, and Podcast Tracks projected from
the current Active iPod. Podcast Episodes and current device membership are runtime
projections and are never serialized in the subscription document.

The module owns normalized Podcast and Episode identities, deterministic document
encoding, bounded RSS/Atom and directory clients, and catalog reconciliation. The
Podcast Controller is the Qt-facing asynchronous adapter: it rejects stale work and
publishes typed snapshots but does not expose device paths or feed-parser objects.
The GUI may project every subscription's Episodes into one newest-first All Podcasts
view, but each row retains its source Subscription and Episode identities so edits
remain ordinary catalog operations rather than synthetic persisted feed state.
Remote Podcast covers use a separate byte-bounded asynchronous artwork controller;
the GUI consumes owned RGB pixels and never performs network I/O. Device-recovered
Artwork IDs remain an ephemeral projection and reuse the existing iPod artwork
pipeline instead of being written into the subscription document.
The Device Coordinator performs fingerprint-checked writes through Storage to the
two independent versioned documents under
`iPod_Control/iOpenPod/Podcasts/`. Existing malformed or future-version documents
are preserved and make Podcast state read-only. See ADR-0037.

Podcast media download, retention, and device publication do not belong to this
module's document writer. They must enter the common Library Draft, review, and
Storage Transaction workflow before changing iPod media or iTunesDB.

#### `app/synesthesia`

Contains the independent whole-file musical-understanding boundary used by
Synesthesia presentation. `MusicAnalysisBackend` accepts a private temporary
audio-file path, an immutable `AnalysisRequest`, cancellation checkpoints, and
typed progress reporting. It returns one immutable, runtime-only `TrackAnalysis`;
it does not receive transport position, an Active iPod, Playback Controller, or
presentation policy.

`TrackAnalysis` is organized into energy, rhythm, spectrum, timbre, harmony,
spatial, layer, and structure domains. Its `AnalysisTimeline` provides calibrated
and Track-relative energy, seven fixed frequency-band levels, power balance and
flux, onset and pulse evidence, confidence-gated tempo and pitch, stereo space, and
spectral and timbral motion. Complete-Track Sections carry acoustic summaries and
recurrence-derived motif labels. Typed events represent onsets, beats, downbeats,
Section boundaries, and Source activity. Each continuous signal fixes its timing,
unit, validity, and independent confidence.

The deterministic analyzer is always usable. It exposes harmonic and percussive
acoustic families but does not claim literal instrument identity. In `ENRICHED`
mode, optional HTDemucs separation may replace them with vocals, drums, bass, and
other Sources. Provider absence or failure becomes a typed issue rather than Job
failure. `STANDARD` is the explicit deterministic-only compute budget. Additional
learned analysis uses the `AnalysisEnricher` seam and may contribute only typed
Sources, events, and provenance; it cannot replace calibrated core evidence or
prescribe visual behavior.

FFmpeg decodes the temporary encoded copy directly into bounded memory once per
Job. Track-derived PCM, separated waveforms, and Track Analyses are never written
by this module and no cache lookup exists. Installed model weights are static
application resources and may remain in their model-provider stores. See ADR-0042,
ADR-0046, and ADR-0051.

`SynesthesiaController` is the Qt-facing asynchronous adapter that consumes this
boundary. It runs one Job at a time, provides cooperative cancellation, rejects
stale completion, and publishes the current runtime-only result. While the page is
active, it also prepares one upcoming Playback Entry behind the current Job and
retains that result in memory. Matching occurrence identity, Track, and analysis
request allow a completed result or unfinished Job to become current without
starting over. Queue changes invalidate obsolete preparation; leaving the page
releases both current and prepared state. For each requested Track,
its worker opens an independent, identity-bound `PlaybackSource`, materializes the
encoded bytes in an application-owned temporary Host file, and removes that file on
every exit path. It owns no audio output or transport and does not receive the
Playback Controller. Playback position and Transport Epoch remain GUI integration
concerns and do not enter the analysis backend. See ADR-0078.

#### `app/playback`

Contains the replaceable audio-output boundary. `PlaybackBackend` accepts transport
commands and reports playing state, position, completion, and structured failure
events. Every start and reported event carries a monotonic runtime Playback Attempt
identity; `PlaybackController` discards events that do not belong to its active
attempt. Track identity is not a sufficient correlation key because duplicate Track
occurrences are valid and a decoder can deliver events queued by an earlier source.
The backend does not own Playback Queue, Playback History, or Player presentation.
`QtPlaybackBackend` is the production adapter and privately owns `QMediaPlayer`,
`QAudioOutput`, the `QIODevice` bridge required by Qt Multimedia, and the QObject
relay that translates Qt signals into attempt-tagged backend events.

The backend starts a Track from a seekable Playback Source supplied by the
Application Layer; it never receives an Active iPod, Filesystem Session, Mount
Point, or absolute Host path. An iPod Playback Source translates Qt's random-access
reads into bounded Storage range reads through the current Filesystem Session and
verifies the source file identity. This allows another decoder/output backend to
replace Qt without changing Player widgets, Queue models, History models, or device
access policy.

`PlaybackController` sits above this boundary. It owns Queue and History policy,
chooses the current Track, delegates play, pause, seek, stop, and volume commands,
and treats backend state and position events as authoritative. A backend completion
event advances History or consumes the next queued occurrence. A source or backend
failure leaves the failed Track current and exposes a recoverable Application Layer
error to the GUI. Its read-only `next_entry` exposes the same upcoming occurrence
that Next selects: forward History first, then the head of the Playback Queue.

`LyricsController` observes the current Track without controlling playback. It
publishes known semantic lyrics immediately and honors explicit Library Draft
clears. When the Lyrics tab is visible and the text is unknown, a single worker
reads native lyric tags through an independent Playback Source. Mutagen receives a
read-only seekable adapter with byte and operation limits rather than a Host path
or complete media copy. Request tokens and cancellation prevent an old result
from replacing the current Track's lyrics. Loaded text remains presentation state;
it does not edit the Library Snapshot or device. The pane preserves plain text,
provides translated empty/loading/failure states, and permits selection and copying.

Host Now Playing surfaces and dedicated media controls sit beside the Playback
Backend boundary. `SystemMediaBridge` publishes immutable controller-owned state to
an optional System Media Session and routes typed Host transport intents back
through `PlaybackController`. A native session never calls the backend, receives a
Playback Source, or owns Queue and History policy. macOS uses MediaPlayer Now
Playing and remote-command APIs, Windows uses System Media Transport Controls, and
Linux uses MPRIS on the desktop session bus. Missing or failed native integration is
non-fatal and falls back to a null session. Album artwork is requested lazily through
`ArtworkController` and crosses this boundary as bounded immutable RGB888 bytes;
each native adapter owns and caches its Host-specific conversion. See ADR-0018.

#### `app/services`

Contains application use cases and orchestration.

Examples:

```python
DeviceCoordinator
SyncService
BackupService
PodcastService
ArtworkService
TranscodingService
```

Services coordinate lower-level modules.

The device-loading seam is `DeviceCoordinator`. It translates Storage discovery into
path-free Device Candidates only after a read-only check confirms the
`iPod_Control` marker, gathers current hardware and on-device metadata as Device
Evidence, asks Device Registry for an Identification Result, and owns the one Active
iPod Filesystem Session. Ordinary removable media remains visible only to Storage.
Discovery is read-only. Selection repeats identity and database checks and, for an
exact profile on a write-safe Volume, may run the narrow Device Metadata
Reconciliation workflow before opening the retained read-only session and reading a
fingerprinted database snapshot. `IPodLibrary` accepts bytes rather than paths,
preserving the rule that only Storage accesses device filesystems. Its common
Library Snapshot enters application state; retained database documents remain
private to the source adapter.

Device Metadata Reconciliation is deliberately idempotent and authority-last. The
Registry produces desired bytes; the Application asks Storage to atomically publish
changed SysInfo and SysInfoExtended files, then publishes
`iOpenPodSysInfoAuthority`, reads all three back, and flushes the Volume. Authority
hashes make an interrupted prefix untrusted on the next pass, so the workflow can be
replanned safely. A read-only Volume remains loadable and reports that repair was
skipped. This bounded cache repair does not substitute for a Storage Transaction and
does not authorize Sync, deletion, or database mutation.

`DeviceController` is the thin Qt adapter around that non-visual service. It runs
discovery, device reads, and parsing through an owned single-worker `QThreadPool`,
then applies immutable results to Qt models through queued signals on the GUI
thread. It also persists the Volume Identity after a successful selection and chains
an exact remembered match from discovery into the same background selection path.
Widgets depend on this adapter and never receive a Mount Point or Filesystem Session.

When global settings contain a previously selected Volume Identity, startup runs one
background discovery pass and attempts the ordinary selection workflow for an exact,
ready match. This pass does not start polling while the Device Picker is closed.

Device Picker visibility owns automatic discovery on all three operating systems.
Opening the picker starts a pass; the controller schedules the next pass two seconds
after completion and defers while device operations hold a reservation. Closing the
picker stops scheduling, allowing an in-flight read to finish. Automatic passes reuse
ready candidates only while their complete mounted observations are unchanged and
retry unready candidates. They preserve the current Active iPod object and publish
changed discovery results only. Manual Refresh repeats metadata inspection. Search
feedback and retry details remain inside the picker. This polling loop does not
replace native lifecycle subscriptions or authorize additional device writes. See
ADR-0069.

For playback and analysis, `DeviceCoordinator` supplies a requested Track's opaque Playback
Source. It resolves the Track's Device Path from the authoritative Active iPod
Library, checks that it remains beneath `iPod_Control`, captures its file identity,
and services bounded range reads through Storage. It does not decode media or own
transport policy.

Artwork presentation follows the same composition. Selection gives already-read
ArtworkDB bytes to `IPodLibrary`, which privately builds the Artwork Index and links
Track projections by their source identities. A visible request asks
`DeviceCoordinator` to supply the Active iPod's typed cover capabilities to the
source adapter, then Storage reads only the returned byte range. `ArtworkController`
deduplicates and decodes requests through a small worker pool, rejects obsolete
Connection Generation results, and bounds retained RGB bytes by memory rather than
item count. The GUI owns the final QImage and QPixmap conversion.

Track-table artwork remains part of that model/view flow. `TrackColumn.ARTWORK` is a
real logical column, while its GUI delegate reads only typed artwork ID and
placeholder-seed roles. The delegate requests a reduced thumbnail during visible
cell painting; it does not inject cells, allocate row widgets, or inspect ArtworkDB.

Artwork editing remains semantic and source-bound. Storage captures an explicitly
selected ordinary Host image into a stable, bounded snapshot; a background
Application Layer worker applies encoded orientation and returns owned RGB888 pixels.
The Track metadata editor stages a square crop rather than a temporary file or a
database record. Multi-Track selections receive one shared artwork relationship. A
mixed selection can instead retain one of its existing artwork identities through a
grid that combines byte-identical decoded images. Metadata and the explicit
replace, clear, or retained-cover artwork intent enter `LibraryWorkspace` through
one revision-checked operation, so the draft publishes at most once and validation
cannot leave a partial metadata edit or orphan asset. The GUI never chooses
ArtworkDB or iTHMB formats; iPodDB derives those device-specific representations
during the existing reviewed save workflow.

Photos use the same boundary composition without sharing ArtworkDB identity.
Selection supplies optional PhotosDB bytes to `IPodLibrary`, which publishes an
optional semantic `PhotoLibrary` and retains the document privately. A UI request
uses `DeviceCoordinator.load_photo`; the coordinator supplies the selected Device
Profile's Photo formats, validates the chosen relative path beneath `Photos/`, and
reads only that range through Storage. The UI receives immutable RGB888 pixels and
never receives a PhotosDB Chunk tree, Mount Point, or Filesystem Session. Supported
Photo and Photo Album edits use the existing source-bound Library Draft and reviewed
Storage Transaction. `PhotoController` performs generation-scoped asynchronous
loading and bounds retained RGB bytes; `PhotoPixmapProvider` performs GUI-thread Qt
conversion. The Photos page composes one three-pane horizontal splitter: a semantic
Photo Album list, an `EqualizedGridView`-based virtualized Photo grid, and a read-only
inspector. Its exact format buttons extend the typed Photo Request rather than
opening device paths, and its grouped metadata comes only from `PhotoLibrary`. A
Photo with a retained full-resolution reference also exposes a Full res chip. The
Application Layer validates and reads that ordinary image through the active
Filesystem Session, applies its encoded orientation, and downsamples it to the
physical-pixel request before it enters the byte-bounded RGB cache.
The selected-Photo context menu opens one user Photo Album membership dialog. Its
`EqualizedGridView` collection cards request at most four retained member Photos
through that same provider and paint an overlaid circular check control. The rendered
card is the control's activation target and does not become selected. Each toggle uses
`LibraryWorkspace` to stage a validated membership change; the Master Photo Album is
absent, and a changed Workspace generation closes the dialog. Bulk selection uses
checked, unchecked, and mixed states without changing unrelated membership order.
The same context menu and Ctrl+E open a Photo metadata editor for the supported
rating, original-date, and taken-date fields. Multi-Photo mixed values remain
unchanged unless explicitly edited, and `LibraryWorkspace` validates and publishes
the complete selected batch as one revision-checked Library Draft edit. Source size
and retained representation facts remain read-only in the dialog.
The Photos page header also owns one **New Album** action. It collects a name and
stages an empty user Photo Album through the revision-checked Library Workspace. The
Device Registry supplies the non-master MHBA type required by the selected iPod;
iPodDB validates that creation policy and appends one typed album Chunk without
rebuilding retained albums. The action is unavailable without a readable Photo
Database or while the Workspace is locked, and creation never writes directly to
the device.
The selected-Photo context menu also confirms deletion of one or many Photos. One
revision-checked `LibraryWorkspace` operation omits the Photos and every occurrence
from all Photo Albums, including the Master Photo Album, and records explicit
omission intent. iPodDB removes the corresponding MHII and MHIA records while
preserving the relative order and retained bytes of every survivor. The Application
Layer captures unique, unshared full-resolution files only beneath
`Photos/Full Resolution`; the reviewed Storage Transaction publishes PhotosDB before
moving those files into recovery. Packed Photo iTHMB files are not compacted or
removed.
Selected Photos and complete Photo Albums share the serialized Host-export controller
used by Tracks and Playlists. `DeviceCoordinator` resolves and pins a readable
full-resolution file beneath `Photos/`, then Storage streams it to a create-only Host
destination. It also supplies every exact retained iTHMB representation supported by
the current Device Profile as RGB888, and the Application Layer encodes each as an
ordinary JPEG. Every Photo export creates a uniquely named per-Photo folder; Photo
Album export places those folders beneath a uniquely named collection folder.
Existing Host files and folders are never overwritten. The GUI receives semantic
Photos and progress rather than device paths. See ADR-0053, ADR-0054, ADR-0055,
ADR-0056, ADR-0057, ADR-0058, and ADR-0059.

For example:

```text
SyncService
    ↓
Device Registry
    determines device capabilities

iPodDB
    builds/updates database structures

Storage
    performs safe writes/copies/deletions
```

A service is the appropriate place to express workflows such as:

```text
scan device
load database
compare library
build sync plan
show review
execute transaction
verify
commit
eject
```

The GUI should call services rather than directly manipulating databases or filesystems.

---

The Application Layer derives desktop presentation from the saved Master Playlist
name and the Device Profile's packaged image when the global **Manage iPod drive
appearance** setting is enabled (the default). Off skips companion capture and all
appearance mutations, preserving user customizations. The Device Controller applies
the persisted setting before startup selection and forwards changes to the
coordinator. Policy changes invalidate pending Library preparation and review
authority; an executing operation completes under its original policy. Selection
provisions portable volume companions after the Library loads, and name edits include
their changed bytes in the reviewed Library Storage Transaction. Discovery and unsaved
drafts do not write
presentation. Native labels and the macOS icon flag follow verified publication as
repeatable derived metadata; failures produce diagnostics and retry on selection.
See ADR-0090 and `docs/volume-presentation.md` for the platform contract.

### `iOpenPod/assets`

Contains static application resources.

```text
assets/
├── fonts/
├── glyphs/
├── images/
└── ipod_images/
```

### `iOpenPod/GUI`

Contains all QWidget-based presentation code.

```text
GUI/
├── delegates/
├── dialogs/
├── pages/
├── synesthesia/
├── widgets/
└── presentation/
    ├── artwork_provider.py
    ├── photo_provider.py
    ├── device_images.py
    ├── display.py
    ├── i18n/
    └── theme/
```

The GUI should remain a consumer of application state and services rather than the owner of application logic.

Library Drafts are an internal application concept. Editors use ordinary editing
labels. The Draft all changes setting explains its manual-review and immediate-save
choices; other labels, tooltips, confirmations, and status messages omit draft-only
explanations. Review Changes and Save to iPod remain available when the setting is
on. Automatic application is the default when it is off. See ADR-0073.

`SynesthesiaPage` is an internal graphics-only route with no Sidebar entry. The
Player exposes its sole entry action above the current Track rating. Activating that
action opens the page and starts a Musical Analysis Job for the current Playback
Entry without sending any transport command. While active, the page observes
`PlaybackController` position, playing state, current-entry changes, and explicit
seeks. It also prepares `next_entry`, coalescing Queue and History changes until the
current-entry transition has settled. A successor promotes matching preparation
or starts a replacement Job; same-entry metadata reconciliation does not restart
current analysis. Preparation progress and failures stay quiet. Leaving the page
cancels both Jobs and releases their analysis state without changing audio playback.

While the page is visible, F or F11 toggles fullscreen. Fullscreen hides the Player,
Sidebar, Queue/History/Lyrics pane, and status bar so the renderer fills the display.
F, F11, or Escape restores the previous window geometry and chrome visibility.
The existing renderer and playback remain active throughout this presentation
change; leaving the page or closing the window also restores the normal shell.

The page contains only `SynesthesiaRenderer`. Analysis progress and failure may use
the application-wide status surface, but file selection, source labels, transport
controls, timelines, Section annotations, and analysis readouts do not overlay the
graphics. It starts a Synesthesia Preview from the current Track identity
and Player clock immediately, without decoding audio. On successful analysis, it
installs `TrackAnalysis`, aligns the running clock with the Player's latest
timestamp, and blends analyzed forcing and Scene direction into the live field.
The Coupled Field, GPU state, feedback, and Transport Epoch remain continuous.
See ADR-0051, ADR-0068, and ADR-0078.

`GUI/synesthesia` is the visual-instrument boundary. `FieldConductor` samples the
typed Track Analysis, applies reliability once, owns force-specific attack and
release, and emits renderer-neutral `FieldForcing`. Energy, low-frequency mass,
fine excitation, harmonic coherence, chroma-derived palette, spectral brightness
and flux, timbral noise, stereo width and pan, beat phase, Source activity, and
Section development remain separately addressable controls. It crosses an impact
at most once in a Transport Epoch, skips event backlog when a seek starts a new
epoch, and permits an intentional recross in that new epoch. A deterministic
whole-Track salience plan admits onset and rhythmic display events independently of
renderer sample cadence, suppressing micro-clusters before they can become a
permanent overlay.

`SceneDirector` is a second frontend presentation component. It derives a
presentation-only Mood Signature from interval summaries, upper-transient evidence,
and local event density, follows Section boundaries after a two-second minimum
hold, groups shorter Sections, divides longer spans into at most 22-second cues,
chooses among the procedural Scene vocabulary, and owns deterministic diversity and
crossfade policy. Tolerance-valid Section bounds are normalized into an exact,
contiguous cue partition. Every
residence also carries typed Scene Motion: a normalized direction, travel and orbit
rates, depth velocity, waveform gain, parallax, and world scale. Inside the
residence, the same component privately composes bounded Camera Shots with an
editorial kind, identity, position, target, roll, and field of view. It may move an
interior edit only within a bounded window to trustworthy musical punctuation. It
may not add Scene, mood, palette, motion, camera, or renderer controls to the
analysis backend. A Mood Signature is an artistic control vector, not inferred
listener emotion or genre.

`SynesthesiaRenderer` is both the QRhi Rendering Adapter and the deep live
`CoupledField` implementation. Stable CPU state contains the experience seed, a few
force-pole identities, transport context, an idempotent impact ledger, and integrated
visual motion phases. The renderer advances those phases with unpaused field time,
so changes in musical or Scene rates affect future movement without rescaling
previous travel. The phases survive seeks, analysis handoff, and GPU resource
rebuilds, and reset with a new field. Four phase vectors extend the shared uniform
contract to 140 floats.
High-volume particles and evolving field buffers remain GPU-resident. Compute
passes update particles through attractor/repulsor forces, curl-like turbulence,
pressure waves, charge, and organization. Spectral, spatial, Source, and Section
controls modulate those shared dynamics. A procedural Scene pass establishes the
current composition using one of twelve grammars: Magnetosphere, Ribbon Cascade,
Warp Tunnel, Mirror Wave, Prismatic Veil, Lattice Cathedral, Solar Bloom, Star
Chamber, Contour Drift, Crystal Shoal, Braided Current, or Signal Rain. Selection
keeps at least six mood-ranked alternatives before excluding the three most recent
Scenes, extending Solar Bloom's exclusion to five residences, and separating
consecutive radial compositions. Cumulative usage balances the eligible pool.
Subsequent graphics passes expose ambient matter, velocity-aligned comets,
electrical filaments, and typed transient phenomena for onsets, downbeats, Section
boundaries, and Source entrances. Scene-specific gains may fully suppress a shared
projection so the silhouettes do not collapse back into one effect stack. The
particle pass reveals a stable, activity-dependent subset of the simulation, and
comet visibility ramps up gradually, preserving visual headroom at moderate
activity. Scene residence timing and particle restraint follow ADR-0077. The
transient pass uses retained Field Impulse identity, while every impulse also
perturbs the particle simulation. Dense onsets are admitted through a salience and
refractory policy, while rare strong beats may become restrained laser accents when
downbeat evidence is unavailable. Scene Motion drives the procedural Scene's world
coordinate system; a renderer-ready Camera Pose comes only from the Scene Director.
The dominant Scene reconstructs a camera ray and samples target-focused,
camera-facing slices at bounded offsets from the subject distance, so it shares
perspective and parallax with the Coupled Field without placing a nominal layer
behind an oblique camera. The QRhi NDC orientation is explicit in the uniform
contract so the same Camera Pose remains upright across graphics backends. A
musical deformation curve assembled from rhythm phase, rhythmic pulse, onset
strength, energy, spectrum, layers, and timbral flux bends Scene geometry;
directional feedback advection makes retained light reveal rather than obscure the
path of travel, and bounded camera motion reduces retention before an old viewpoint
can smear across a new framing.

The renderer uses ping-pong storage buffers, instanced camera-facing quads,
offscreen render targets, restrained temporal feedback, and portable QShader
packages. QRhi uses Direct3D 11 on Windows, Metal on macOS, and OpenGL on Linux.
Quality tiers may change particle count, field resolution, or postprocessing cost,
but not the coupled-field architecture. Resource loss reconstructs disposable
detail from stable genesis behind a fade; exact particle identity and retained
pixels are not application semantics.

The visual acceptance run spans a complete Track. It must demonstrate materially
different silhouettes and motion languages whose selection remains connected to
local musical evidence. Scenes are procedural and transitions are directed; there
is no authored video, asset progression, literal narrative, or clock-driven preset
shuffle. Pause freezes simulation; seeking preserves live field state while
clearing view-dependent feedback and reanchoring musical evidence without event
backlog. The renderer receives no NumPy
arrays, mutable analysis dictionaries, or device access; its only analysis model is
the typed, immutable Track Analysis. See
[Synesthesia visual direction](synesthesia_visual_direction.md), ADR-0045,
ADR-0047, ADR-0048, ADR-0049, ADR-0050, and ADR-0051.

---

#### `GUI/delegates`

Contains Qt item-view delegates.

Delegates customize rendering and editing inside:

```text
QTableView
QListView
QTreeView
```

Delegates may request already-indexed presentation artwork through the shared
provider while painting visible items. They must not decode artwork, inspect an
ArtworkDB, or create a persistent widget per model row.

They should generally subclass:

```python
QStyledItemDelegate
```

Examples:

```python
RatingDelegate
ArtworkDelegate
ProgressDelegate
BadgeDelegate
```

Typical responsibilities:

- custom cell painting
- rating stars
- artwork thumbnails
- progress indicators
- specialized editors
- custom formatting

Delegates should be used instead of embedding large numbers of persistent child widgets inside item views.

Use the native capabilities of `QHeaderView` for ordinary column movement, resizing,
sorting, keyboard use, and accessibility before introducing a custom table header.
Any custom item painting must be limited to the viewport and must not allocate
persistent widgets as the collection grows.

---

#### `GUI/dialogs`

Contains modal or transient UI workflows.

Examples:

```python
TrackEditorDialog
SyncReviewDialog
MediaFoldersDialog
PreferencesDialog
DeviceInfoDialog
```

Dialogs may coordinate with application services but should not implement the underlying business logic.

For example:

```text
SyncReviewDialog
    displays SyncPlan

SyncService
    creates and executes SyncPlan
```

The dialog owns presentation and interaction.

The service owns the operation.

---

#### `GUI/pages`

Contains primary application screens shown inside the main navigation/page stack.

Examples:

```python
AlbumsPage
ArtistsPage
PhotoPage
TracksPage
PlaylistsPage
PodcastsPage
DevicePage
BackupPage
SettingsPage
```

Pages should primarily compose reusable widgets and connect them to application models/services.

Avoid rebuilding the same visual patterns independently on every page.

---

#### `GUI/widgets`

Contains reusable QWidget components.

Examples:

```python
AppButton
IconButton
SearchField
Card
AlbumCard
DeviceCard
Sidebar
SidebarItem
SettingRow
SettingGroup
SegmentedControl
StatusBadge
ArtworkView
PhotoInspector
CollapsibleSection
TrackTable
```

Widgets should encode reusable application UI concepts.

Prefer semantic variants such as:

```text
primary
secondary
danger
warning
selected
```

instead of appearance-specific component names such as:

```text
BlueButton
RedButton
DarkCard
```

Reusable widgets should draw from the global theme/palette rather than hard-coding colors.

---

#### `GUI/presentation`

Contains application-wide presentation infrastructure.

```text
presentation/
├── artwork_provider.py
├── display.py
├── image_color.py
├── i18n/
└── theme/
```

---

##### `GUI/presentation/display`

Owns the process-wide Qt display policy that must be established before
`QApplication` is created. Qt 6 performs native high-DPI scaling; application layout
uses device-independent logical pixels, typography uses positive point sizes derived
from Host system font metrics, and raster backing stores follow each screen's Device
Pixel Ratio. Widgets do not branch on the Host platform or apply production scale
environment variables. Vector or Device-Pixel-Ratio-aware assets are required when
icons and artwork are introduced.

---

##### `GUI/presentation/i18n`

Owns internationalization and runtime language switching.

Potential contents:

```python
I18nManager
LocaleFormatter
```

and translation resources such as:

```text
translations/
├── iopenpod_de.qm
├── iopenpod_fr.qm
└── ...
```

Responsibilities include:

- loading `QTranslator`
- installing/removing translations
- changing language at runtime
- locale-aware formatting
- propagating language-change events
- managing default/system locale behavior

Widgets with static user-facing text should support retranslation.

A typical reusable widget can implement:

```python
def retranslate_ui(self): ...
```

and respond to:

```python
QEvent.LanguageChange
```

Application identifiers should never rely on translated strings.

Use stable enum/data values and translate only their display labels.

---

##### `GUI/presentation/theme`

Owns the visual theme system.

The working palette, metric, typography, state, and cross-platform rules are
documented in [`gui-design-language.md`](gui-design-language.md). That contract is
independent of the prototype page composition, which remains replaceable.

Potential contents:

```python
ThemeManager
Theme
IconProvider
PaletteBuilder
StylesheetRenderer
```

Themes should use semantic tokens:

```text
window
surface
surface_alt
surface_hover
surface_pressed
surface_selected
text
text_secondary
text_disabled
border
border_strong
accent
accent_hover
accent_pressed
accent_ink
focus
danger
warning
success
```

rather than scattering literal colors throughout widgets.

The theme system should support the appearance modes:

```text
System
Light
Dark
```

and determine the effective theme centrally. Light and Dark each have an independent
exact-theme setting, so Auto/System mode can select the configured Porcelain Light
theme or either the Slate or Original iOpenPod Dark theme without conflating Host
appearance with palette identity.

Optional Colorful Mode uses a generic image-to-color presentation helper. The lazy
artwork provider computes colors outside the GUI thread and retains them in an
entry-bounded least-recently-used cache scoped to the Connection Generation. Only
Library-card delegates and the active Track-list context bar consume that value.
Delegates use it for quiet card fills; models and lower-level boundaries continue
to expose images and identities rather than GUI colors.

The recommended division is:

```text
QPalette
    fundamental application colors

QSS
    widget-specific visual styling

ThemeManager
    switching and orchestration
```

Most widgets should update automatically when the global palette or stylesheet changes.

Only custom-painted or dynamically generated assets should need direct theme-change handling.

---

## Cross-Module Responsibilities

The cleanest boundary between the four modules is:

## `Storage`

> How do I safely access this device and filesystem?

```text
devices
volumes
mounts
paths
reads
writes
copy
move
transactions
eject
```

## Device Registry (Recap)

> What iPod model is this and what can it do?

```text
identity
generation
capabilities
hardware metadata
format support
device definitions
```

## `iPodDB`

> How are iPod database files represented, parsed, and serialized?

```text
ArtworkDB
iTunesDB
binary records
parsers
writers
validation
```

## `iOpenPod`

> What should the application do with all of this?

```text
application workflows
sync
backup
playback
library management
models
GUI
theme
i18n
```

---

## Example Device Workflow

Connected iPods flow through the system like this:

```text
1. Storage detects removable devices
                ↓
2. Storage exposes physical/volume identifiers
                ↓
3. iOpenPod asks Device Registry to identify candidates
                ↓
4. Device Registry returns Device Profiles
                ↓
5. Device Picker presents candidates to the user
                ↓
6. User selects one Active iPod, or iOpenPod restores the remembered selection
                ↓
7. iOpenPod opens a Storage Filesystem Session
                ↓
8. iOpenPod reads database bytes through Storage
                ↓
9. iOpenPod gives those bytes to iPodDB
                ↓
10. iPodDB publishes a common immutable Library Snapshot
                ↓
11. Application Layer exposes state to the GUI
```

For writing:

```text
1. Application Layer scans and correlates Host and iPod media
                ↓
2. User selects desired Host media and optional iPod-only removals
                ↓
3. Application Layer derives an immutable selected Sync Plan
                ↓
4. User examines the plan in Sync Review
                ↓
5. iPodDB constructs/serializes updated database bytes
                ↓
6. iOpenPod gives the bytes and file operations to Storage
                ↓
7. Storage Transaction stages file changes
                ↓
8. Storage verifies and commits the changes
                ↓
9. Storage removes/trashes obsolete files
                ↓
10. iOpenPod updates GUI and application state
```

---

## Dependency Direction

The architecture should preserve this dependency direction:

```text
                    ┌─────────────────┐
                    │    iOpenPod     │
                    │ App + GUI       │
                    └───────┬─────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
      Device Registry     iPodDB       Storage

```

Let `iPodDB` only parse/serialize bytes and have `iOpenPod` perform all persistence through `Storage`:

```text
iPodDB
    bytes ↔ structured database

iOpenPod
    orchestration

Storage
    safe bytes ↔ filesystem
```

That provides the strongest decoupling.

---

## Architectural Rules

1. **`Storage` contains no iPod-specific knowledge.**
2. **Device Registry describes devices; it does not own filesystem access.**
3. **`iPodDB` owns binary database-format knowledge.**
4. **`iOpenPod` owns application workflows and orchestration.**
5. **GUI code never directly manipulates device files.**
6. **The Application Layer calls `Storage` for device mutations.**
7. **Models expose state; they do not perform arbitrary destructive I/O.**
8. **Parsers parse; writers serialize.**
9. **Safe persistence is a `Storage` responsibility.**
10. **Theme and i18n remain presentation concerns.**
11. **Reusable GUI components live under `GUI/widgets`.**
12. **Custom item-view rendering/editing lives under `GUI/delegates`.**
13. **Platform-specific device filesystem behavior stays inside `storage/platform`.**
14. **Application code should not branch on `sys.platform` outside platform infrastructure.**
15. **Lower-level modules must never depend on `iOpenPod`.**
16. **An unchanged iPod database round trip reproduces the original bytes exactly.**
17. **Unknown Data is retained and does not imply corruption.**
18. **Only one user-selected Active iPod is loaded at a time.**

This arrangement keeps device knowledge, database knowledge, storage safety, and application behavior distinct while still allowing the four modules to cooperate through narrow, explicit interfaces.
