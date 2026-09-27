# iOpenPod Context

## Purpose

iOpenPod is a cross-platform desktop application for managing filesystem-accessible
iPods without iTunes. The long-term product will browse and edit an iPod library,
plan and apply media synchronization, preserve device-specific database behavior,
and protect removable media from unsafe writes.

iOpenPod 2.0 is a deliberate rebuild of the Original iOpenPod. There is no reduced
"first usable version" that defines the product's final scope. Development may be
incremental, but it continues toward feature parity with the Original iOpenPod and
then beyond it.

## Current stage

iOpenPod 2.0 is in its foundation and binary-format implementation stage. Current
binary-format work includes definition-driven, lossless parser/writer foundations
for iTunesDB, ArtworkDB, and PhotosDB. PhotosDB exposes the on-device Photo Database
as a root-typed artifact over the evidenced ArtworkDB-format nested Chunk and MHOD
layouts. Every database artifact uses the same mandatory, header-typed Chunk
Definition contract, one root-typed Database Definition, and the same shared
structural reader/writer path. These
foundations remain subject to review as broader application workflows establish
their stable public interfaces. The repository also contains an architecture draft
and exploratory application settings and database-definition code whose public
interfaces and internal layout are not yet settled. Treat
`docs/source_architecture.md` as the target direction and untested source as evidence
and experimentation, not as completed implementation.

This stage prioritizes shared language, documented decisions, a reproducible Python
environment, consistent verification tools, and careful implementation of the iPod
database formats as device-writing workflows become available.

Storage now has a generic mounted-volume and Filesystem Session foundation with
native snapshot discovery for Windows, macOS, and Linux, plus a virtual-volume test
adapter. It can also return generic SCSI VPD and Host property observations from an
identity-bound Physical Device without interpreting them as iPod facts. Its current
macOS adapter correlates each `diskutil` BSD whole-disk identity with generic USB
identifiers from IOKit before the Application Layer interprets that evidence. Its
mutation surface includes verified single-file operations, recoverable trash, and
ordered multi-file Storage Transactions with retained originals and durable Operation
Journals. Transactions validate unchanged dependencies, stage verified content,
publish writes before removals, and support explicit restoration after reconnecting.
Storage now also performs user-directed native safe removal through Windows Plug and
Play, macOS Disk Arbitration's `diskutil` client, and Linux UDisks2. It never forces
an unmount, preserves native refusal details, and models an unmounted-but-not-ejected
partial result by expiring the Connection Generation. Incoming-media planning/import
and event-driven connection monitoring remain prerequisites for general Sync and
destructive maintenance workflows. See ADR-0029 and ADR-0060.

The Application Layer now coordinates device discovery and selection through
`DeviceCoordinator`. It reads identity metadata and iTunesDB snapshots only through
Storage, translates generic Host observations into Device Evidence, asks Device
Registry to identify each Device Candidate, gives already-read database bytes to
iPodDB, and owns one Active iPod Filesystem Session. Discovery never writes. When the
Application Layer builds a discovery snapshot, only mounted Volumes containing the
`iPod_Control` marker become Device Candidates; ordinary removable media stays a
Storage observation and never reaches the Device Picker. When the user selects an
exactly identified iPod, a narrow metadata-reconciliation workflow
can atomically repair SysInfo, SysInfoExtended, and the version-1
iOpenPodSysInfoAuthority record on a write-safe Volume before the Library is loaded.
The repair is verified, flushed, idempotent, and does not authorize Sync or any
destructive workflow.
`DeviceController` runs discovery and selection outside the Qt GUI thread and
publishes immutable results to the shared library models. If a previous Volume
Identity is saved, startup makes one background discovery pass to restore that iPod.
On Windows, macOS, and Linux, opening the Device Picker starts discovery immediately
and repeats it two seconds after each pass while the picker stays open. Closing it
stops further picker passes. Searching feedback stays inside the picker, and
unchanged observations preserve the Active iPod and Library Draft. Native
event-driven connection monitoring remains separate future work. See ADR-0069 and
ADR-0071. After a successful selection, it stores the selected Volume Identity in
global settings. Discovery automatically restores that choice only when exactly one
matching Device Candidate is ready; the connection-scoped Device Candidate ID is
never persisted.
The GUI first opens a modal folder dialog that stages Host Media Library folders and
their recursive, per-media-type scan settings. Accepting the dialog persists that
configuration in global settings, starts a cancellable background Host Media Scan,
and opens the full-window Sync Workspace for scan progress, media selection, and
Review. The scan covers audio, video, Photos, and Playlists and projects the result
through the common Library Snapshot API,
calculates and caches bounded raw Chromaprint fingerprints for Host Tracks and
SHA-256 content fingerprints for Host Photos, discovers embedded or common
folder-level Track artwork for lazy source-validated display, and
explicitly reviews Playlist references outside the selected media catalog, including
excluded media types and subfolders. M3U/M3U8, PLS, XSPF, WPL, and ASX/WAX/WVX
documents use bounded Storage reads; only explicitly accepted local audio/video
references can extend the scan, through identity-checked private Storage captures.
Network references, nested Playlists, links, and XML entity declarations cannot
expand access. Host file and folder-artwork churn during scanning is retained as a
diagnostic instead of failing the best-effort scan; Sync revalidates current source
facts before writing. See ADR-0074 and ADR-0082. On completion,
the workspace presents a read-only, source-isolated Host browser made from the same
Album, collection, Track, Playlist, Photo, and media-category pages as the iPod
browser. The normal sidebar stays iPod-focused, and the Active iPod Library Draft is
never replaced. See ADR-0063, ADR-0064, and ADR-0067.
When an Active iPod is available, the pre-Sync workflow next runs an iPod Media Scan.
It reads a checksummed Library Sync Helper from
`iPod_Control/iOpenPod/library-sync-helper.json`, reuses entries whose persistent
identity and cheap device-file facts still match, and fingerprints only missing or
stale Tracks and full-resolution Photos. Newly discovered media gets no invented Sync
history; Sync Details are written only after a successful Sync commit. The
helper remains matching evidence rather than Library or mutation authority. The
pre-Review scan does not persist it; successful Sync publishes its new provenance
after the verified Library commit. The Application Layer then
prepares an immutable Sync Plan for Tracks and full-resolution Photos. Proven Host
path relationships are considered before unique content identities; current Host
size and modification time are compared with the Host facts recorded by a successful
prior Sync to distinguish Update from In sync. The initial comparison classifies
Host-only media as Add and iPod-only media as Remove, while missing or ambiguous
identities remain Needs attention. The Select Media stage defaults correlated Host
items on and Host-only items off, supports aggregate Album and collection selection,
and can group grid items as Selected, Mixed, or Deselected. Opening an Album or
collection card in Select Media replaces the browser with a full detail page,
including artwork, metadata, bulk selection, and the shared Track table with its
own search. Back returns to the retained browser; these Sync pages have no split
Track pane. The global **iPod Library View Mode** setting also offers this shared
presentation in the iPod browser as **Whole Page Table**, without Sync Selection
controls. **Split Table** remains its default. Changes apply immediately and are
saved across restarts. See ADR-0072. Review derives an
immutable selected Sync Plan in collapsible change groups; iPod-only removal
candidates start unchecked. Review can exclude individual actions or whole groups
without changing desired Host membership. Sync Selected validates that plan, checks
required media tools, prepares compatible media on the Host, and builds an isolated
Library Draft. Failed independent items are reported and excluded while successful
items can still commit. The verified Library and media publish through Storage;
successful Sync Details follow the commit. Cancellation and interrupted publication
have explicit cleanup/recovery results. See ADR-0065 through ADR-0067, ADR-0070,
and ADR-0076.
Interrupted Sync recovery is a choice for the selected iPod: restore the previous
Library or explicitly keep current contents after a warning about incomplete
changes. Recovery and cleanup are discovered from device journals, never persisted
as Host settings. Declining restoration retains recovery copies and leaves media
and databases untouched; unrelated iPods remain usable. Successful Library saves
automatically clean their committed recovery files; Sync does so after attempting
its Library Sync Helper update. Selection also cleans matching completed
transactions after checking all journals for unfinished recovery. Discovery stays
read-only, and foreign or declined journals remain untouched. Only actual cleanup
failures require a cleanup warning and retry. See ADR-0089 and ADR-0093.
Optional acoustic analysis no longer gates readable Host media or explicit Adds.
Sync checks media tools only for incoming Tracks and preserves committed Host-path
provenance independently of Acoustic Fingerprints in Library Sync Helper v3.
Embedded artwork uses seekable reads, including for large audiobooks. Successful
FFprobe output remains usable with incidental metadata diagnostics. Preparation
reports all concurrent Tracks with separate phase progress measured from FFmpeg's
output time and speed, and groups repeated informational conversion notices. Normal
Play Counts and On-The-Go positional data is preserved or remapped in the same
Storage Transaction as the Library, with unchanged bytes retained wherever possible.
Oversized Photo containers become bounded PNG stills, with separate Host and iPod
content digests. Publication verification and automatic recovery report their
current files; verified restoration cleanup retries do not repeat media reads.
macOS AppleDouble companions are excluded from artwork dependencies, and cleanup
tolerates entries already removed by filesystem metadata maintenance.
See ADR-0084 through ADR-0087 and `docs/sync-workflow-audit-2026-09-26.md`.
Compressed iTunesCDB and SQLite-backed iPod Library variants are selected from the
identified Device Profile. iPodDB unwraps and reproduces CDB framing and treats the
CDB as the sole readable Library authority. It generates all five SQLite databases
and the Locations checksum book from the checked CDB snapshot and supports HASH58,
HASH72, and HASHAB finalization. Selection neither requires nor reads SQLite
companions. When a CDB change is prepared, the Application Layer captures the
current companion paths as write preconditions and publishes the CDB, the complete
replacement SQLite set, and compatibility iTunesDB truncation in one recoverable
Storage Transaction. See ADR-0061.
Recognized Device Profiles now include typed artwork formats and packaged product
images. Selection optionally loads ArtworkDB metadata, while visible album covers
are read from iTHMB ranges and decoded lazily through a generation-scoped,
memory-bounded artwork pipeline. Missing or malformed artwork falls back to the
deterministic placeholder without making an otherwise valid iPod Library unusable.
Known cover-capable Device Profiles also provide the creation policy for a first
ArtworkDB, so an empty Artwork directory needs no template database or additional
format files. Preparation writes every declared cover layout, preserves retained
variants, and supports older reverse Track links. See ADR-0033.

Selection also loads an optional `Photos/Photo Database` into the common Library
Snapshot as an immutable Photo Library. The Application Layer can request a Photo
thumbnail lazily by semantic Photo identity and Device Profile format; Storage reads
only the validated range beneath `Photos/`. Malformed optional PhotosDB metadata is
reported without making an otherwise usable iPod Library unavailable.

The Photos route is a three-pane browser with Photo Albums on the left, the shared
virtualized Library card grid in the center, and a read-only Photo inspector on the
right. Selecting a Photo loads only its visible device representation through a
generation-scoped, byte-bounded worker cache. The inspector can request an exact
format copy and offers a Full res chip when the semantic Photo retains an original.
That original is read through Storage and downsampled before entering the display
cache. The inspector shows grouped semantic metadata without receiving a PhotosDB
Chunk, Mount Point, or Filesystem Session. Selected Photos export to a chosen Host
folder; Photo Albums and All Photos export into a uniquely named child folder. Readable
full-resolution files are copied byte-for-byte through Storage. Every exported Photo
gets its own folder containing that original when available and an ordinary JPEG for
each retained, supported iTHMB format. Exports never replace existing Host files,
run outside the GUI thread, and can be cancelled safely between files. See ADR-0054,
ADR-0055, and ADR-0056. The selected-Photo context menu also opens one Manage Albums
dialog. Its collection-card grid previews up to four Photos per retained user Photo
Album and overlays a large circular membership checkbox. Single and bulk membership
toggles are Library Draft edits persisted through the shared automatic or manual
review/save workflow. Dragging selected Photos from the grid onto
a user Photo Album in the sidebar adds only missing memberships through that same
draft workflow. Existing memberships remain unchanged; All Photos, stale drags, and
locked workspaces reject drops. The same context menu opens a revision-bound
Photo metadata editor for rating, original date, and taken date. Mixed values remain
unchanged unless the user edits that field, and a multi-Photo apply publishes one
atomic Library Draft revision. See ADR-0053 and ADR-0057.

Library Snapshots now use a common immutable Track contract that is constructed by
both iPod and Host Media Library Sources and can support future remote sources. iPod database translation
and lossless documents remain inside iPodDB; GUI and application models consume
semantic values rather than database flags or Chunk trees. Optional iPod Track
Details retain diagnostic values without requiring other sources to invent them.
See `docs/library-contract.md` and ADR-0019.

Library Snapshots also contain semantic Playlists, Smart Playlists, nested Playlist
Folders, and the name read from an unambiguous Master Playlist. The browser uses
saved membership and a sidebar hierarchy, while creation and editing operate on
internal Library Drafts. Editors use ordinary editing labels. The global
**Draft all changes** setting defaults to off: Library edits are automatically
prepared, accepted, and saved through the existing verified Storage Transaction,
and the sidebar hides Review Changes. On restores Review Changes and manual Save
to iPod. Turning it off also applies pending changes. Failed or blocked attempts
retain the draft and open diagnostics without repeatedly retrying that revision.
See ADR-0073. The internal workspace contracts from ADR-0020 and ADR-0026 remain.
Typed Playlist Sort Orders and per-occurrence Playlist
Positions are parsed, shown, edited, recalculated, and written through the same
lossless path. Applying changed Smart Playlist rules also updates saved matching
Tracks. Regular Playlists accept Track drags; folders retain nested
organization. The firmware-maintained Podcasts Playlist remains in the Library
Snapshot and Library Workspace for reconciliation but is omitted from the sidebar
tree. Unsaved drafts clear when the Active iPod changes or the application closes.
See ADR-0020 and ADR-0022 for hierarchy and editor behavior.

The Library Workspace retains Photos and Photo Albums in that same desired snapshot.
Retained Photo rating/dates and retained user Photo Album names, membership,
slideshow settings, and music Track references use the existing source-bound Library
Draft, review, preparation, and safe-save contract. The Photos header can create an
empty user Photo Album using the selected Device Profile's explicit MHBA type policy;
the new album uses the same automatic or manual safe-save policy. User Photo Album
deletion requires explicit omission intent. Selected Photos can also be omitted from
the Photo Library and every Photo Album as one reversible draft edit. Preparation
removes their MHII/MHIA references, while Save recoverably removes only unshared
full-resolution files beneath `Photos/Full Resolution` after PhotosDB publication.
Unused ranges in shared iTHMB files are retained. Sync can now create or replace
Photos with a captured original and every supported Device Profile thumbnail
format, including a first Photo Database where the profile declares its creation
policy. It preserves original image bytes, applies rotation and fitting to viewing
copies, and removes only fully unreferenced obsolete Photo files after publication.
Direct arbitrary Master Photo Album edits and deletion remain blocked. See
ADR-0053, ADR-0058, ADR-0059, and ADR-0076.

Library Draft preparation now compares complete desired snapshots with retained
Database Documents, maintains supported Track/Playlist/Photo/artwork relationships,
and
returns verified bytes and structured diagnostics. Preparation runs in the
background and rejects stale or cancelled results. With Draft all changes on,
Review Changes labels success Prepared for review and Save to iPod requires manual
acceptance; with it off, acceptance is automatic. Both modes commit verified
metadata, device-name, Playlist, Photo, artwork, and Track-removal changes through a
captured Storage Transaction with retained originals and a recovery journal. General Sync stays
disabled. Missing device-bound signing material, unsupported ArtworkDB signatures,
pending positional sidecars, and ambiguous affected structures block preparation.
See ADR-0021, ADR-0022, ADR-0061, and `docs/library-writing.md`.
Preparation requests capture source and workspace revisions together. Read-only
developer inspection exposes changes, requirements, observed stages, output
fingerprints, and diagnostics without exposing private document bindings or granting
save authority. See ADR-0023.
Semantic resolution now accounts for requested edits and generated consequences
before reconciliation. Explicit field ownership, independent browse-index checks,
and the existing review's resolved-value inspection strengthen that workflow without
changing the editing or saving scope. See ADR-0025.
Library Drafts also accept explicit media replacement intent when projected
metadata stays unchanged. Preparation validates the supplied media, verifies native
codec output, and returns captured file dependencies. Application replacement
capture and publication remain unfinished. See ADR-0034.

Lyrics edits now require verified text embedded in the media file as well as the
iTunesDB presence flag. The Application Layer prepares focused lyric-tag updates;
Storage publishes them with the database in one recoverable transaction. This is
independent of optional full metadata writing for Rockbox compatibility. Unrelated
edits preserve file-only lyrics, and incoming music reads embedded lyrics into its
draft. See ADR-0075 and `docs/research/itunesdb-lyrics.md`.

Backup Snapshots use Backup Archive format v4, continuing the Original iOpenPod v2
and v3 format sequence, with lossless
Device Paths, serial-first Backup Identifiers, checksummed catalogs, and deduplicated
Host content. A known product or transport serial identifies the iPod; otherwise a
hashed Volume Identity supplies a best-effort fallback rather than blocking backup or
restore. Capture hashes new and changed files during their single Device-to-Host
stream, reuses previously verified content when path, size, and modified time still
match, and finishes with a metadata-only tree rescan. Original iOpenPod backup formats
v2 and v3 enter only through a read-only Legacy Backup Import to v4. Restore is
authorized separately from archive location, first creates a forced Host safety
snapshot, and executes as one bounded, journaled Storage Transaction whose recovery
material remains in that Host archive. Verified completion, pre-mutation failure,
incomplete restore, and durability pending are distinct user-visible outcomes. Backup
and restore remain independent of Sync and other application workflows. Capture
blocks Application Layer device writes and Active iPod changes while allowing
foreground reads such as browsing, artwork, export, and playback; Restore remains
exclusive. An Original archive whose serial key matches the Active iPod is assigned
that iPod's native Backup Identifier and Archive Key, preventing imported and native
snapshots from splitting into separate sidebar devices; unmatched and explicitly
unstable imports retain their stricter legacy authorization. See ADR-0039, ADR-0040,
ADR-0041, and ADR-0062.

The Podcasts browser now projects a typed Podcast Snapshot from versioned
subscriptions, independent Listening History, refreshed RSS/Atom metadata, and the
current Active iPod's Podcast Tracks. Existing device Podcasts are recovered into
subscriptions automatically; enclosure-based reconciliation exposes current
on-device membership immediately, while listened state survives later Track removal
or unsubscription. The GUI can search Apple's public directory, add direct RSS
feeds, immediately refresh a show when it is opened, mark episodes listened or
unlistened, and play Tracks already on the iPod. Its All Podcasts view combines
every subscription's Episodes newest-first while retaining each Episode's source
identity; it is a runtime projection, not another persisted Podcast Subscription.
Device files use
fingerprint-checked Storage writes under
`iPod_Control/iOpenPod/Podcasts`. Podcast Episodes can be added or removed manually,
and per-show Sync settings select and retain Episodes during ordinary Sync or the
Sync Podcast and Sync Podcasts actions. These operations refresh feeds, preserve
Listening History, prepare compatible media on the Host, and publish through the
shared verified Library and Storage Transaction workflow. Failed feed refreshes
leave that show's media unchanged. Publisher covers use the shared ArtworkDB and
thumbnail preparation; Podcast Sync also fills missing covers on retained Episodes
without downloading their media again. Episode slots are an automatic filling target;
manual additions may exceed it. Episode count alone never authorizes removal.
Both Newest and Next clear by listened state or time on the iPod. Newest replaces
only clear-eligible Episodes with newer publications. Next starts after the furthest listened
publication, or with the oldest available Episode when no listened publication is
known. Replace waits for successful one-for-one replacement, including above the
target; Remove clears eligible Episodes even without replacements.
Listening History retains publication chronology and separate automatic-clear
exclusions. These exclusions prevent automatic re-addition without marking an
unlistened Episode listened; explicit additions bypass them. Pre-Sync reconciliation
saves observed history, while new exclusions commit in the same verified Storage
Transaction as successful media and Library removals. Subscription and Listening
History documents encode version 2 at their existing paths and still read version 1.
See ADR-0037 and ADR-0091.

The Library Workspace now holds Track metadata, the device name, Playlists, and
Photos in one session draft. Sidebar naming, shared Track and collection context
menus, and
a manual metadata editor apply explicit changes to this draft. Normalize Tags scans
the Library in the background using Original iOpenPod's grouping and sorting rules,
previews the results, and applies them only on request. A shared, debounced background
scan keeps the Normalize Tags Sidebar badge current with the number of suggested
tag-field edits. Opening or closing the preview reuses that scan; applying changes,
editing, locking, or switching the Active iPod invalidates old results. Mixed metadata, stale
dialogs, and cancelled scans cannot silently overwrite current edits. The save
workflow now stages artwork, Track removals, and full-resolution Photo removals
alongside database changes. Shared context menus can remove Tracks as reversible
draft edits; the Photos context menu stages confirmed Photo deletions through the
same workflow;
the Track metadata editor can choose, orient, square-crop, replace, clear, or
consolidate its selection onto one existing cover and submits that intent atomically
with metadata. Its consolidation grid combines byte-identical decoded artwork.
Application callers can also supply bounded artwork pixels. Backend music import
inspects supplied compatible songs, extracts embedded covers, and adds a reversible
draft for the existing review/save workflow. Music import has no GUI entry point,
file picker, or progress dialog. Application media replacement remains unfinished.
The Track context menu can also reclassify retained
audio or video as a Podcast without replacing its media; the existing review/save
path writes its firmware classification, playback flags, presentation fields, and
Podcasts Playlist consequences. The metadata editor's Media type selector also
reclassifies retained audio or video within its current media family, including
Movie to TV Show, atomically with explicit metadata and artwork edits. Mixed and
retained compound classifications stay unchanged until selected for replacement.
Podcasts and videos always use Remember position and Skip when shuffling in
application imports, edits, and prepared Library Drafts. Save and Sync repair
retained Tracks with those flags off. Audio and video Podcasts also enable the
native Podcast Now Playing marker. Merely loading an iPod preserves its raw
database state. See ADR-0026, ADR-0030, ADR-0032, ADR-0036, ADR-0088, and ADR-0092.

The application can now inspect real incoming audio/video files through FFprobe
over a temporary Host snapshot captured by Storage. Typed Media Inspection preserves
all streams, embedded-picture dispositions, exact rational timing, chapters, and
tags independently of Library classification. Inspection has cancellation, process
and output limits, and content fingerprints. Music import applies a bounded audio
compatibility policy and maps observed facts into native codec fields. The same
reviewed transaction stages the song, thumbnails, ArtworkDB, and iTunesDB before
publication. Sync preparation accepts Host-native path spelling, chooses marked-
default or first-probe-order streams from multi-stream video, and scopes encoder
options to the selected FFmpeg encoder while reporting those choices as warnings.
Exact gapless analysis, conversion, the Sync engine, video import, and document
inspection such as PDF/EPUB remain future work. See ADR-0031, ADR-0032, and ADR-0083.

Playback is an Application Layer workflow behind a typed, replaceable Playback
Backend. `PlaybackController` owns runtime Queue, History, current Track, and
transport policy; the GUI only sends intents and renders reported state. The
production backend adapts Qt Multimedia. It receives a seekable Playback Source
rather than a Mount Point or Host path, and each source range is read through the
Active iPod's identity-bound Filesystem Session. A changed Active iPod, Connection
Generation, or media-file identity fails closed. Queue, History, volume, and
transport state remain runtime-only. Monotonic Playback Attempt identities correlate
backend events with the active start so delayed decoder events cannot mutate a
successor Track. An optional System Media Session sits above that controller and is
independent of the Playback Backend. The macOS and Windows adapters publish Track
metadata, timeline, state, and lazily loaded album artwork through their native media
surfaces and route media commands back through the controller. Artwork remains bounded
RGB888 data until each native adapter converts and caches it. Linux publishes the
same fail-open contract through MPRIS on the desktop session bus.

The Library setting **Double click shortcut** applies immediately to Track tables,
Album cards, and collection grids and lists and persists across restarts. **Add to
queue** remains the default. **Play next** places the selection atop the Playback
Queue. **Play now** starts the first selected Track and places the remainder atop
the Queue. **Edit** opens the metadata editor for the selection. Selections retain
visible order and Playlist occurrences; explicit queue buttons keep their own
actions.

The Player's Queue/History/Lyrics slideout displays read-only lyrics for the
current Track. Known Library text and explicit draft clears take precedence;
otherwise the visible Lyrics tab loads embedded media tags in a background worker
through the same identity-bound Playback Source. Reads are bounded, obsolete
results are discarded, and missing or unreadable lyrics do not interrupt playback.

Synesthesia is entered from the Player while a Track is current; it has no sidebar
entry or separate page controls. The Playback Controller and Playback Backend
remain the only owners of audio and transport, so playback continues while
Synesthesia analyzes the current Playback Entry and prepares the next entry while
the page is active. Preparation follows the Player's Queue and forward History,
retains at most one upcoming result in memory, and is promoted when that entry
becomes current. Leaving the page releases both analyses. The Qt-facing Synesthesia
Controller opens a separate,
identity-bound Playback Source, materializes its encoded bytes only in an
application-owned temporary Host file, runs one Job at a time outside the GUI
thread, rejects stale completion, and always removes that temporary copy. It
publishes one ephemeral, calibrated Track Analysis with absolute and relative
energy, rhythm, spectrum, timbre, harmony, spatial evidence, structural Sections,
musical events, and typed Sources behind one sampling interface with explicit
confidence and provenance. The Field Conductor preserves energy, spectrum, rhythm,
harmony, stereo space, Sources, and Section development as independent typed Field
Forcing.

The frontend Scene Director derives a presentation-only Mood Signature and directs
twelve procedural visual Scenes across Sections and bounded subspans. Scene changes
follow Section boundaries with a two-second minimum hold, grouping only shorter
Sections. Long Sections retain subspans of at most 22 seconds. Recent Scenes have a
cooldown, with
extra spacing for Solar Bloom and radial compositions;
contours, crystal shards, braided currents, and falling signals expand the visual
vocabulary. Scene-specific gains change which shared particle, comet, filament, and
event systems are visible. Particle density and comet visibility build gradually
with activity, leaving room for musical peaks. Each residence also receives Scene
Motion for directional travel, orbit, depth,
waveform deformation, parallax, and world scale. Inside each residence the Scene
Director composes establishing, tracking, orbital, inspection, fly-through, and
reveal Camera Shots from interval summaries, upper-transient evidence, and sparse
event density. The renderer projects both the
procedural composition and shared three-dimensional field through that directed
pose, while feedback advects retained light along the journey and erodes during
meaningful camera travel. Transitions and nearby editorial edit points are
deterministic and music-weighted rather than a random preset timer or beat-pulsed
lens. The graphics-only page observes the Playback Controller's current position
and playing state. Pause freezes the simulation; an explicit Player seek begins a
new Transport Epoch, preserves live field state, clears view-dependent feedback,
and does not replay a skipped event backlog. A Synesthesia Preview follows
the current Playback Entry immediately without reading audio. When Track Analysis
finishes, the renderer aligns with the Player clock and blends its forcing and
Scene direction into the existing field without resetting GPU state. The analysis
backend remains independent of transport and presentation policy, and no
Track-derived evidence, stems, simulation state, or feedback is persisted. See
ADR-0042, ADR-0045, ADR-0046, ADR-0047, ADR-0048, ADR-0049, ADR-0050, ADR-0051,
ADR-0068, ADR-0077, ADR-0078, `docs/synesthesia_backend.md`, and
`docs/synesthesia_visual_direction.md`.

With **Manage iPod drive appearance** enabled (the default), selecting a writable
iPod also derives desktop names and model icons from its saved
Master Playlist name and Device Profile. Renames update portable Windows, GVfs,
KDE, and macOS icon companions through the Library's recoverable save workflow.
Storage updates native volume labels and the macOS custom icon flag after file
publication. Native limitations are reported without undoing a saved Library name;
filesystem label limits never change the full iPod name. Turning this global setting
off preserves custom companions, icons, native labels, and Finder flags across
selection and saved renames. See ADR-0090 and
`docs/volume-presentation.md` for platform limits and verification status.

## Product and compatibility target

- The Original iOpenPod is the behavioral and research baseline. Its code,
  documentation, tests, fixtures, and accumulated format knowledge are evidence for
  iOpenPod 2.0, not a runtime dependency or an architecture that must be copied.
- The release target is Windows, macOS, and Linux.
- The standard native macOS candidate targets 12.3 or later on Apple Silicon and
  Intel with platform-specific Qt and numerical dependencies. Build selection and
  binary deployment checks enforce that target; execution on macOS 12.3 on both
  architectures remains an acceptance gate. See ADR-0094 and `docs/packaging.md`.
- Planned store channels are the Mac App Store, Microsoft Store, Flatpak/Flathub,
  and Snap. Native packaging candidates are available; store publication remains
  gated on signing, sandbox-compatible Storage access, user-installed media-tool
  integration, and installed-package acceptance. FFmpeg/FFprobe and Chromaprint's
  fpcalc executables are installed separately by the user; Qt's playback libraries
  remain bundled. See `docs/packaging.md`, ADR-0079, and ADR-0081.
- The release target includes filesystem-accessible iPod families supported by the
  Original iOpenPod: full-size iPod generations 1 through 5.5, iPod Classic, iPod
  Mini, and iPod Nano across their supported generations. iPod touch and iPod
  shuffle are outside this target.
- iOpenPod ships as one application and one distribution. Device Registry, iPodDB,
  and Storage are internal packages, not separately released products.
- Development and automated testing use captured database fixtures, virtual device
  volumes, and knowledge from the Original iOpenPod instead of writing to a physical
  iPod as part of routine verification.

## System boundaries

| Boundary | Responsibility | Must not own |
| --- | --- | --- |
| **Storage** | Safe, cross-platform access to devices, volumes, filesystems, and removable-media operations | iPod identity, database formats, application workflows, or GUI behavior |
| **Device Registry** | Identification and capability descriptions for known iPod models | OS discovery, mounting, filesystem mutation, database parsing, or GUI behavior |
| **iPodDB** | Parsing, representing, validating, and serializing iPod database formats | Device persistence, application workflows, or GUI behavior |
| **iOpenPod** | Application orchestration, state, services, and GUI behavior | Platform filesystem implementations or duplicated database-format knowledge |

The intended dependency direction is:

```text
iOpenPod ──> Device Registry
         ├─> iPodDB
         └─> Storage
```

Storage, Device Registry, and iPodDB do not depend on iOpenPod. iOpenPod coordinates
them through narrow interfaces.

## Application operating model

- Storage may discover multiple connected iPods, but the user chooses one in the
  Device Picker and iOpenPod loads only that Active iPod.
- Only one Active iPod exists in the application at a time. Selecting another iPod
  ends the previous Filesystem Session and begins a new Connection Generation.
- Sync is primarily Host-to-iPod: the Host Media Library supplies the media and most
  metadata used to update the iPod Library.
- iPod-to-Host behavior is also supported. This includes Back Sync of ratings and
  other supported metadata, exporting iPod-only tracks, and exporting images.
- Long-running work occurs outside the GUI thread, reports progress, and supports
  cancellation where stopping is safe. The exact worker mechanism is not yet fixed.
- If the Active iPod disconnects, iOpenPod invalidates its Filesystem Session and
  stops issuing operations. It cannot guarantee rollback while the Volume is absent;
  it must report that the operation may be incomplete and require a new selection or
  reconnection before continuing.

## Data locations

- The Host Media Library remains in the folders selected and owned by the user.
- iPod media and databases remain on the Active iPod and are accessed only through a
  Filesystem Session.
- Global settings, logs, caches, and temporary files use the standard application
  locations for Windows, macOS, and Linux. Global settings are one typed JSON file;
  Storage resolves its Host location and atomically persists its bytes while
  iOpenPod owns the settings schema. iOpenPod 2.0 uses `settings-v2.json`; it does
  not read or rewrite the Original iOpenPod's `settings.json` file in the same Host
  directory.
- Global settings remember the previously selected iPod by stable Volume Identity.
  This behavior has no separate visible preference.
- Sync recovery records and retained originals stay on the iPod. They are
  operational data and do not belong in global settings.
- Backup Snapshots use the configured backup location, with a platform-appropriate
  application data location as the default.
- Device-specific settings intended to travel with an iPod are associated with its
  stable Device Identity and stored in an application-owned Device Path on that iPod.
  iOpenPod coordinates their access through Storage. Podcast Subscriptions and
  Listening History use separate version-2 JSON documents under
  `iPod_Control/iOpenPod/Podcasts/`, retaining the existing `-v1.json` filenames and
  backward reads of version 1; other settings retain their own formats.

## Core device workflow

1. Storage detects removable Physical Devices and their Volumes.
2. iOpenPod keeps Volumes containing `iPod_Control`, reads device metadata, and
   requests identity-bound Host observations.
3. iOpenPod passes normalized Device Evidence to Device Registry.
4. Device Registry returns an Identification Result and, when exact, a Device
   Profile with Device Capabilities.
5. The GUI presents Device Candidates in the Device Picker.
6. The user selects one candidate as the Active iPod, or iOpenPod restores the
   previous selection when exactly one ready candidate has the remembered Volume
   Identity.
7. On a write-safe Volume, iOpenPod analyzes, atomically repairs, and verifies stale
   or missing identity metadata; read-only Volumes remain loadable with an issue.
8. iOpenPod opens a read-only Filesystem Session through Storage.
9. iOpenPod reads database bytes through Storage and gives them to iPodDB.
10. iPodDB parses and retains lossless Database Documents in the iPod Library Source,
    then publishes a common immutable Library Snapshot.
11. The Application Layer exposes that snapshot and application state to the GUI.

For review, iOpenPod submits a Library Draft and asks iPodDB to prepare supported
semantic changes against its retained Database Documents. Typed Chunk Selections
and the matching writers remain the one lossless path. Future physical Sync will
use a Storage Transaction to stage, verify, and commit the resulting filesystem
changes. Constructing, editing, or preparing a Library Snapshot does not authorize
or perform device writes.

Backup Snapshots are a standalone, user-controlled protection. The implemented
backup and restore workflow does not participate in Sync, Library save, or any other
device workflow; those operations retain their own Storage safety requirements.

## Safety invariants

- A Mount Point is a temporary location, not a Device Identity.
- A Filesystem Session becomes invalid when its connection ends.
- Device-facing paths are relative, root-bound, and traversal-safe.
- iPodDB returns or consumes data and bytes; it does not mutate device files.
- Parsing and serializing an unchanged database must reproduce its original bytes
  exactly, including unknown fields, unknown Chunks, ordering, and padding.
- Unknown database data is expected and preserved. It is not treated as corruption
  merely because iPodDB does not understand it.
- Destructive operations are planned, validated, journaled, verified, and made
  recoverable where practical.
- Obsolete files are removed only after replacement data has been verified.

## Development constraints

- iOpenPod uses GPL-3.0-or-later, with free distribution and optional donations.
  Releases must preserve third-party notices and provide corresponding source;
  store compatibility remains a separate release requirement. See ADR-0080 and
  `docs/licensing.md`.
- Python 3.12 is the only supported development runtime.
- UV manages Python, the environment, dependencies, the lockfile, and commands.
- VS Code and Codex Desktop are the development surfaces.
- Ruff, Mypy, Pytest, and Rumdl provide formatting, linting, type checking, and
  testing from one UV-managed environment.
- `pyproject.toml`, `.editorconfig`, and `.vscode/` keep terminal and editor behavior
  consistent across development machines.
- Branded names retain their established capitalization where practical, including
  iOpenPod, iPodDB, iTunesDB, ArtworkDB, and iPod. Generic Python package and module
  names use normal lowercase conventions.

## Documentation map

- `GLOSSARY.md` defines canonical terms.
- `docs/source_architecture.md` describes the detailed target architecture.
- `docs/ipoddb-editing.md` defines the sole typed parse/edit/write workflow.
- `docs/adr/` records durable decisions.
- `docs/agents/` configures agent-oriented engineering workflows.
- `.scratch/` holds private, uncommitted plans and work items.

## Open questions

- What is the smallest stable public interface for each boundary?
- Which existing exploratory modules should be retained, rewritten, or removed?
- Which Original iOpenPod behaviors should be migrated together as complete vertical
  workflows, and in what order?

These questions are intentionally unresolved. Resolve them through focused design
work and ADRs before reorganizing the source tree.
