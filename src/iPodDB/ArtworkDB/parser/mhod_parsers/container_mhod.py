from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType
from iPodDB.ArtworkDB.shared.mhod_payload_spec_registry import MHOD_DEFINITIONS
from iPodDB.shared.chunk import UnknownChunkHeader, chunk_as
from iPodDB.shared.chunk_reader import parse_chunk
from iPodDB.shared.diagnostics import retain_unknown_bytes
from iPodDB.shared.errors import UnexpectedHeaderMarkerError, UnknownMhodLayoutError
from iPodDB.shared.types import MhodPayloadParseContext


def parse_container_payload(
    context: MhodPayloadParseContext[None],
) -> MhodContainerPayload:
    # Deferred while the parser registry is being assembled from payload parsers.
    from iPodDB.ArtworkDB.parser.parser_definition import PARSER_DEFINITION

    mhod_type = ArtworkMhodType(int(context.mhod_type))
    required_child_definition = MHOD_DEFINITIONS[mhod_type].container_child_definition
    if required_child_definition is None:
        raise ValueError(
            f"ArtworkDB MHOD type {int(context.mhod_type)} is not a container"
        )

    child, next_offset = parse_chunk(
        context.data,
        context.payload_offset,
        parser_definition=PARSER_DEFINITION,
    )
    if next_offset > context.payload_end:
        raise ValueError(
            f"ArtworkDB MHOD type {int(context.mhod_type)} MHNI child extends "
            f"past its container: {next_offset:#x} > {context.payload_end:#x}"
        )

    if isinstance(child.header, UnknownChunkHeader):
        raise UnknownMhodLayoutError("unrecognized image-container child")
    if child.generic_header.header_marker != required_child_definition.marker:
        raise UnexpectedHeaderMarkerError(
            f"expected {required_child_definition.marker!r}, "
            f"got {child.generic_header.header_marker!r} at {child.offset:#x}"
        )

    return MhodContainerPayload(
        child=chunk_as(child, required_child_definition.header_type),
        trailing_data=retain_unknown_bytes(
            context.data,
            next_offset,
            context.payload_end,
            f"MHOD {int(context.mhod_type)} container suffix",
        ),
    )
