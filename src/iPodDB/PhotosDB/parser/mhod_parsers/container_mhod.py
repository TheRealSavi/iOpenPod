from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.PhotosDB.shared.constants import PhotosMhodType
from iPodDB.PhotosDB.shared.mhod_payload_spec_registry import MHOD_DEFINITIONS
from iPodDB.shared.chunk_reader import parse_chunk_as
from iPodDB.shared.types import MhodPayloadParseContext


def parse_container_payload(
    context: MhodPayloadParseContext[None],
) -> MhodContainerPayload:
    # Deferred while the parser registry is being assembled from payload parsers.
    from iPodDB.PhotosDB.parser.parser_definition import PARSER_DEFINITION

    mhod_type = PhotosMhodType(int(context.mhod_type))
    required_child_definition = MHOD_DEFINITIONS[mhod_type].container_child_definition
    if required_child_definition is None:
        raise ValueError(
            f"PhotosDB MHOD type {int(context.mhod_type)} is not a container"
        )

    child, next_offset = parse_chunk_as(
        context.data,
        context.payload_offset,
        required_child_definition,
        parser_definition=PARSER_DEFINITION,
    )
    if next_offset > context.payload_end:
        raise ValueError(
            f"PhotosDB MHOD type {int(context.mhod_type)} MHNI child extends "
            f"past its container: {next_offset:#x} > {context.payload_end:#x}"
        )

    return MhodContainerPayload(
        child=child,
        trailing_data=bytes(context.data[next_offset : context.payload_end]),
    )
