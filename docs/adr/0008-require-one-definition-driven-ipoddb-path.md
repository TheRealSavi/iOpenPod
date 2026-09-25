# ADR-0008: Require one definition-driven iPodDB path

- Status: Accepted
- Date: 2026-08-27

## Context

iTunesDB originally supplied separate list-marker and header-type registries, while
ArtworkDB supplied richer Chunk definitions. The shared reader supported both forms
through optional registry fields and compatibility branches. That made the apparent
shared interface misleading: the two database families could receive different
validation, Unknown Data handling, and writer behavior from the same module.

ADR-0006 requires parsers and writers to share one lossless format contract. Optional
legacy paths weaken that contract and allow new format knowledge to be added to only
one side.

## Decision

- Every known iTunesDB and ArtworkDB Chunk has one mandatory,
  `ChunkDefinition[HeaderType]`.
- A Chunk definition declares its Header Marker, purpose, header type, minimum and
  writable header sizes, extent convention, body kind, and ordered child groups.
- Each family has one `DatabaseDefinition[RootHeaderType]` that identifies its root
  Chunk and aggregates its complete Chunk and MHSD dataset definitions. Parsing and
  writing consume that same object.
- Each parser definition adds the complete MHOD parser selection, including a
  required opaque rule for unknown MHOD types, without duplicating structure.
- The shared reader has no alternate marker-set, header-map, policy-flag, or
  definition-free compatibility path for known Chunks.
- Unregistered Header Markers use one canonical Unknown Data behavior: they are
  retained as opaque, length-delimited Chunks when structurally valid.
- The shared writer owns recursive Chunk structure, validation, length repair,
  child-count repair, and Unknown Data retention. Both database writers call that
  same implementation and provide only their format-specific MHOD body encoder.
- Each parser returns one immutable, root-typed Database Document. Consumers edit it
  through typed Chunk Selections and give that same document directly to the matching
  writer; there is no mutable writer model or conversion layer.
- Every understood MHOD payload shape has one mandatory inverse encoder. Contextual
  payload validation occurs before retained bytes may take the unchanged path.
- New Chunk construction belongs to symmetric family Builder packages that consume
  the same registered definitions; constructors do not live in writer modules.
- Parser and writer packages depend on shared definitions; neither depends on the
  other.

## Consequences

- iTunesDB and ArtworkDB follow the same package and execution pattern even though
  their concrete Chunk and MHOD layouts differ.
- Static analysis and IntelliSense retain the exact header type through Chunk
  definitions, Database Definitions, builders, parsers, Chunk Selections, edits, and
  writers.
- Consumers can replace deeply nested Chunks without manually reconstructing every
  ancestor, while stale selections and Header Marker changes fail explicitly.
- Adding a known Chunk or dataset requires a complete definition before it can be
  parsed or written as understood data.
- Definition omissions cannot silently select older behavior. They select the
  explicit Unknown Data path or fail structural validation.
- Unregistered Chunks are never guessed to be child-count containers; they follow
  the canonical opaque, length-delimited Unknown Data convention.
- Shared reader/writer changes affect both database families and require tests
  through both public parser/writer seams.
