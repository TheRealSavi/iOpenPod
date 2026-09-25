# ADR-0052: Model PhotosDB as a distinct artifact

- Status: Accepted
- Date: 2026-09-14
- Extends: ADR-0006 and ADR-0008

## Context

The iPod's `Photos/Photo Database` uses the same observed MHFD-family Chunk and MHOD
layouts as ArtworkDB, but it is a distinct device artifact with photo albums,
full-resolution references, photo thumbnails, and photo-specific creation policy.
Using the ArtworkDB entry points directly would let callers accidentally serialize
the wrong retained document. Copying every Header field and payload implementation
into a separate family would instead create two sources for equal binary facts.

Original iOpenPod's photo workflow provides the parsing and writing evidence. Its
filesystem access, mutable semantic model, device selection, and binary packing are
not the target architecture.

## Decision

- iPodDB exposes PhotosDB through symmetric Builder, Parser, Shared, and Writer
  packages.
- PhotosDB has a nominally distinct MHFD root Header, one root-typed Database
  Definition, its own Chunk-definition graph, contextual parser registry, and public
  parser/writer functions.
- Nested Header and MHOD payload representations whose binary layouts are identical
  remain shared with ArtworkDB. The common inverse MHOD serializer is used by both
  artifact writers. PhotosDB definitions supply their own purposes and structural
  relationships without repeating the known nested field offsets.
- Each public writer requires its matching root Header type. Equal `mhfd` Header
  Markers do not make ArtworkDB and PhotosDB documents interchangeable.
- The existing definition-driven reader/writer path owns structural validation,
  derived lengths and counts, retained short Headers, Unknown Data, and byte-exact
  unchanged round trips.
- PhotosDB operates only on bytes and Database Documents. Device paths, iTHMB and
  full-resolution file I/O, Device Profile policy, semantic photo reconciliation,
  and publication remain outside this increment.

## Consequences

Photo Database metadata can be parsed, persistently edited, constructed, and
serialized with the same typed workflow as iTunesDB and ArtworkDB. A fixed Original
iOpenPod fixture checks the complete photo, album, format, and path shape and
unchanged byte equality.

The two MHFD-format artifacts retain a small deliberate dependency for equal nested
representations and MHOD encoding. A future binary divergence must introduce a
PhotosDB-specific Header or payload type and definition instead of silently changing
the shared representation. This work does not enable a Photos browser, Photo export,
Photo Sync, or physical device writes.
