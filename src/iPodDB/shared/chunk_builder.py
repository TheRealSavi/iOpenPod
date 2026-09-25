"""Definition-driven construction of new writable Chunks."""

from iPodDB.shared.chunk import (
    ChunkHeader,
    ChunkPayload,
    GenericHeader,
    MhodPayloadPrefix,
    ParsedChunk,
)
from iPodDB.shared.types import ChunkDefinition, DatabaseDefinition


def new_chunk[RootH: ChunkHeader, H: ChunkHeader](
    database_definition: DatabaseDefinition[RootH],
    definition: ChunkDefinition[H],
    header: H,
    *,
    children: tuple[ParsedChunk[ChunkHeader], ...] = (),
    prefix: MhodPayloadPrefix | None = None,
    payload: ChunkPayload | None = None,
) -> ParsedChunk[H]:
    """Construct one new Chunk through its family's registered definition."""

    database_definition.require_registered(definition)
    definition.require_header(header)
    if payload is not None and children:
        raise ValueError("a Chunk cannot contain both a payload and children")
    if definition.body_kind == "children" and payload is not None:
        raise ValueError("a children Chunk cannot contain a payload")
    if definition.body_kind in {"mhod", "opaque"} and children:
        raise ValueError(f"a {definition.body_kind} Chunk cannot contain children")
    if definition.body_kind != "mhod" and prefix is not None:
        raise ValueError(f"a {definition.body_kind} Chunk cannot contain a prefix")

    return ParsedChunk(
        offset=0,
        generic_header=GenericHeader(
            header_marker=definition.marker,
            header_length=definition.default_header_size,
            length_or_child_count=0,
        ),
        header=header,
        children=children,
        prefix=prefix,
        payload=payload,
    )
