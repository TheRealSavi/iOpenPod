# Application-Shell Prototype

## Question

Can iOpenPod 2.0 preserve the Original iOpenPod's recognizable desktop music
library shape while replacing its fragile widget construction with the documented
Application Layer, model/view, theme, settings, internationalization, and
high-DPI foundations?

Run the prototype with:

```shell
uv run python main.py
```

This discovers mounted removable Volumes and presents them through the Device
Picker. It can play supported media, edit the Active iPod through Library Drafts,
and safely eject through the Host's native storage service, but general Sync remains
disabled. Selecting an exactly identified iPod may perform the narrow, verified
identity-metadata repair described by ADR-0013.

## Scope

The first application shell now contains the principal regions expected to make up
the product:

- a persistent, balanced three-zone Player surface, configurable at the top or
  bottom edge, and an optional Queue/History pane;
- a service-backed Active iPod summary and source-list Sidebar;
- a Device Picker showing recognized, unsupported, and unrecognized candidates;
- fixed-size virtualized Album, Artist, Genre, TV Show, and Music Video grids and
  Track lists joined by a user-resizable
  context-and-search handle;
- Artist and Genre list modes with collection selection on the left and matching
  Albums on the right;
- full Track, Audiobook, Movie, and combined Video table pages;
- a Settings page;
- a standalone Backups page;
- a three-pane Photos browser with a virtualized grid and format-aware inspector.

The composition is strongly informed by the Original iOpenPod, but no Original
widget hierarchy, theme implementation, or runtime module is imported. Selected
monochrome glyph paths are carried over as static assets and rendered through the
new palette-aware, Device-Pixel-Ratio-aware icon provider. Device artwork is loaded
and decoded lazily; missing artwork uses deterministic placeholder painting.

## Foundation

`AppContext` remains the composition root. Widgets receive models, services,
settings, Theme, and I18n dependencies explicitly; they do not parse an iTunesDB,
persist settings directly, install translators, or infer device capabilities.

Library views consume the common `iPodDB.library` Track contract. The iPod source
adapter retains database documents privately and normalizes database flags,
timestamps, text records, and artwork relationships before publication. Other
sources can construct the same immutable records without database-format imports
or iPod diagnostic values; see `docs/library-contract.md` at the repository root.

`PlaybackController` owns the runtime-only current Track, Playback Queue model,
newest-first Playback History model, and transport policy. Double-clicking a Track
appends one independently addressable occurrence to the Queue. When idle, the
controller immediately consumes the first occurrence, marks it current, records
that start in History, and delegates decoding and audio output to a typed Playback
Backend. Backend events are authoritative for playing state, position, completion,
and failure when their Playback Attempt identity matches the active start. Delayed
events from a replaced source are ignored. The Queue and History are deliberately
absent from settings and are cleared with a whole-Library reset or application
shutdown.

The production Playback Backend adapts Qt Multimedia behind the controller's narrow
interface. It receives a seekable Playback Source, not a Mount Point or Host path.
`DeviceCoordinator` resolves the current Track against the Active iPod Library and
services the source's bounded reads through Storage while checking the Filesystem
Session and source-file identity. Player widgets know nothing about Qt Multimedia or
device access, so a future backend can replace Qt without changing the controls,
Queue, or History behavior.

`DeviceCoordinator` is the non-visual Application Layer seam across Storage, Device
Registry, and iPodDB. Every on-device read and write uses a validated Device Path
through a Filesystem Session. Device Registry sees only typed evidence and metadata
bytes, iPodDB sees only database bytes, and the GUI sees only path-free Device
Candidates and the Active iPod. Only mounted Volumes with an `iPod_Control` marker
become Device Candidates, so ordinary removable media does not enter the Device
Picker. Discovery is read-only. Selection closes the previous session, optionally
reconciles identity metadata through atomic verified writes, repeats identity and
database checks, reads a fingerprinted database snapshot, parses it, and rejects the
result if the source changed during loading.

`DeviceController` owns a single-worker Qt thread pool. Discovery, filesystem reads,
and parsing occur outside the GUI thread; queued results replace the shared Track
model on the GUI thread. The Device Picker authorizes a selection with an opaque
candidate ID rather than a drive letter or Mount Point.

Global settings use typed definitions and a Storage-backed `settings-v2.json` file
in the conventional configuration location for each Host. The separate name leaves
the Original iOpenPod's `settings.json` untouched. Storage owns platform path
resolution and atomic bytes; iOpenPod owns validation and JSON encoding. Window
geometry, Player position, splitter state, and per-table column order, visibility,
and widths are persisted through the same interface. The Player defaults to the top
edge and moves as one existing widget when the preference changes, so its runtime
playback state is not rebuilt. Each live tab retains its own applicable grid or list
mode while the window remains open. Route and table identifiers are stable
untranslated values, while all route labels, issue summaries, and placeholder
explanations are centralized as translatable presentation copy.

Splitter restoration preserves the user's panel proportions but not obsolete visual
metrics. The current Theme-owned handle height is reapplied after restoration so a
state written by an earlier narrow-handle prototype cannot collapse the Track title
and search surface.

The Browser header names only the active tab. Its search applies to that tab and
preserves a separate Album or Track query. In the split view, the lower title and
search surface is the real `QSplitterHandle`: it names the selected album (or all
Tracks), filters only that Track context, and can be dragged anywhere outside its
text field. It is absent from full Track-list mode.

The Theme Module supports Auto/System, Light, and Dark appearance modes, independent
exact Light and Dark theme selections, and owns the semantic palette, native
point-sized typography, logical-pixel metrics, state styling, and vector glyph
rendering. Optional Colorful Mode adds contrast-safe, image-derived color only to
collection-card fills and the Track-list context bar. See
[`docs/gui-design-language.md`](../../../docs/gui-design-language.md). The shell has
been visually checked in Light and Dark themes at 1× and 2× scale.

## Large-Library Construction

The target for this prototype is 10,000 Tracks. The implementation avoids a widget
per Track or album:

- `TrackTableModel` exposes one Track snapshot, caches normalized search text, and
  emits proportionate row/data signals when stable Track identities allow it.
- Album and collection models aggregate summaries when the Track snapshot changes.
- `TrackFilterProxyModel` and `AlbumFilterProxyModel` provide view-specific filtering
  and sorting without rebuilding widgets. The Browser and context searches update
  those proxies instead of copying their results into page-local collections.
- Album and collection grids use `QListView` batched layout with uniform,
  font-metric-aware item sizes and one `QStyledItemDelegate`; only visible cards are
  painted. Shared cells reserve the current style's scrollbar extent and each batch
  ends on a complete visual row, preventing scrollbar feedback and spacing breaks at
  batch boundaries.
- The Photo grid reuses that same equalized, batched card geometry. Its delegate
  requests only visible Photo thumbnails and preserves non-square aspect ratios;
  Photo Album and selected-Photo state are restored by stable semantic identity
  only within the current Workspace generation. Exact-format failures are shown as
  unavailable and can be retried from the inspector.
- Artist and Genre delegates paint fixed 2-by-2 artwork collages and retain blank
  cells when fewer than four usable covers exist.
- `TrackTable` uses `QTableView`, `QHeaderView`, and model roles. It creates no cell
  widgets. Native header movement and interactive resizing replace the Original's
  custom header machinery.
- Album artwork is a real, movable `TrackColumn` with the same menu and persisted
  visibility behavior as metadata columns. Its delegate requests a reduced,
  display-scale-aware thumbnail only when Qt paints a visible cell.
- The Track metadata editor includes an Artwork page with current or mixed-state
  preview, bounded Host image selection, and a pan-and-zoom square crop. Mixed
  artwork relationships can be consolidated through a grid of unique selected
  covers; byte-identical decoded images appear once. Apply sends metadata plus
  replace, clear, or retained-cover artwork intent as one Library Workspace
  revision; no GUI widget writes ArtworkDB or device files.
- The table preserves source order for its first frame. Sorting begins only after
  the user selects a header, avoiding an unnecessary 10,000-row startup sort.
- Size, bitrate, and play-count columns remain in the model but start hidden so the
  primary browsing columns fit a normal desktop window. Each table's header menu can
  add, remove, move, resize, and reset columns independently.

On the 2026-08-28 development machine, the synthetic 10,000-Track fixture projected
to 1,000 albums in about 25 ms, and the Windows shell reached its first rendered
frame in about 0.4 seconds at both 1× and 2× scale. These observations are diagnostic
evidence, not product performance guarantees. Automated tests verify the 10,000-row
path and the absence of item widgets; they deliberately avoid brittle timing
thresholds.

## Explicit Placeholders and Limits

The Player and `PlaybackController` provide transport, seek, Queue, and History UI
behavior, while `QtPlaybackBackend` provides actual decoding, clock advancement,
and audio output through the Host's Qt Multimedia installation. Codec and container
support therefore depends on the Qt/FFmpeg runtime available on that Host;
unsupported, corrupt, or protected media reports a playback failure and remains
retryable. On macOS, the optional System Media Session publishes Now Playing
metadata, timeline state, and lazily loaded album artwork and routes native play,
pause, seek, Previous, and Next commands through `PlaybackController`; it does not
depend on `QtPlaybackBackend`. macOS MediaPlayer, Windows System Media Transport
Controls, and Linux MPRIS adapters consume the same application-owned snapshot and
command contract. Playback is currently limited to media in the selected Active iPod
Library. Sync planning now compares completed Host and iPod Media Scans in a
read-only, virtualized Sync Plan page. Plan editing and execution remain disabled.
Safe eject closes playback and iOpenPod filesystem access, then runs as an exclusive
background device operation. The user sees native busy, permission, unsupported, and
partial-unmount failures; “safe to disconnect” appears only after native
confirmation. Unsaved Library Drafts require confirmation before eject. Capability-
bound Sidebar routes are hidden when the Active iPod cannot support them. Selected
Photos and complete Photo Albums export through the background, create-only Host
export workflow. Photo asset mutation remains intentionally unavailable.

Discovery is currently an explicit snapshot at startup or on Refresh; event-driven
connection monitoring is not implemented. Uncompressed iTunesDB libraries can be
loaded. Profiles that require compressed iTunesCDB or SQLite-backed library formats
are detected and shown as unsupported rather than being parsed through an unsafe
fallback.

ArtworkDB is loaded as optional compact metadata during selection. Visible covers
request only their indexed iTHMB range through generation-bound, memory-bounded byte
and decoded-image caches. Placeholder art remains stable for missing or malformed
artwork, so an otherwise valid Library stays usable.

## Verdict

The application-shell question is answered positively. The Original's core layout
can be recovered through reusable iOpenPod 2.0 modules while keeping parsing,
presentation, persistence, and future device behavior on separate sides of explicit
interfaces.

This remains prototype code. Real device iTunesDB loading runs behind the
Application Layer's Qt worker adapter. Event-driven device monitoring, selection
restoration across every future editing workflow, packaged non-English translation
catalogs, non-Qt Playback Backends, Sync execution, and general device mutation
remain future work.
