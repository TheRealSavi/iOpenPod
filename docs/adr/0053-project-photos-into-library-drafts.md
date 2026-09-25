# ADR-0053: Project Photos into Library Drafts

- Status: Accepted
- Date: 2026-09-14
- Extends: ADR-0019, ADR-0021, ADR-0030, and ADR-0052

## Context

ADR-0052 established PhotosDB as a nominally distinct, lossless binary artifact and
deliberately left semantic workflows outside that increment. The application now
needs Photos as UI-consumable state and needs edits to receive the same source
binding, review, validation, verification, and recoverable publication guarantees as
iTunesDB edits.

Exposing PhotosDB Chunk trees to the GUI would couple presentation to binary layout
and let UI code bypass the established Library Draft contract. A separate mutable
photo editor or writer-command list would duplicate revision, deletion-intent, stale
result, and transaction policy already owned by the Library Workspace and
`IPodLibrary`.

## Decision

- `LibrarySnapshot` has one optional source-neutral `PhotoLibrary` containing
  immutable Photos, Photo Albums, representations, and file-format declarations.
- `IPodLibrary.with_photos` parses and privately retains PhotosDB, creates a new
  source revision, and projects only semantic records. The Library Workspace holds
  Photo state within the same complete desired snapshot and edit revision as Tracks
  and Playlists.
- Photo changes flow through `begin_draft`, `analyze`, `prepare`, review inspection,
  save authorization, reparse verification, and source adoption. Preparation derives
  validation again and cannot be authorized by modified plan diagnostics.
- The initial writable surface is retained Photo rating/dates and retained user
  Photo Album name, membership, slideshow settings, and Track-backed music. Explicit
  omission intent permits user-album deletion. Asset-changing operations and Master
  Photo Album editing or deletion remain blocked.
- Photo thumbnails load lazily. iPodDB selects a typed relative range from semantic
  metadata and caller-supplied Device Profile formats. The Application Layer
  validates containment beneath `Photos/`, Storage reads the range, and the UI
  receives immutable decoded pixels. No filesystem authority or binary Chunk enters
  the common contract.
- PhotosDB publication is part of the exact issued Library Review's Storage
  Transaction. Its source fingerprint is checked before preparation and saving;
  successful publication is followed by parsing and adopting a new source.

## Consequences

UI code can browse, inspect, and draft supported Photo changes through one coherent
Library API. Photo-only edits do not cause iTunesDB signing or unrelated ArtworkDB
reconciliation. Unknown PhotosDB data and untouched records retain the lossless
binary guarantees from ADR-0052.

Adding Photos, importing or removing image assets, creating albums, rewriting file
formats, exporting full-resolution files, and a concrete Photos page remain separate
work. Those operations require explicit allocation, capability, file-resource, and
recovery policy before the writable surface can expand.
