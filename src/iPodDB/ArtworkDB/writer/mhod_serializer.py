"""Shared MHOD serialization for ArtworkDB-format database artifacts."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType, MhodPayloadKind
from iPodDB.ArtworkDB.shared.mhod_payload_spec_registry import MHOD_DEFINITIONS
from iPodDB.ArtworkDB.writer.mhod_encoder import (
    encode_mhod_body,
    validate_mhod_body_representation,
)
from iPodDB.shared.binary_struct import parse_binary_struct
from iPodDB.shared.chunk import ChunkHeader, ParsedChunk, chunk_as
from iPodDB.shared.chunk_writer import NestedChunkSerializer


def serialize_artwork_mhod_body(
    chunk: ParsedChunk[ChunkHeader],
    parent_marker: bytes | None,
    serialize_child: NestedChunkSerializer,
) -> tuple[bytes, ChunkHeader]:
    """Serialize an MHOD used by either ArtworkDB-format database artifact."""

    typed_chunk = chunk_as(chunk, MhodHeader)

    try:
        mhod_type = ArtworkMhodType(typed_chunk.header.mhod_type)
    except ValueError:
        definition = None
        payload_kind = MhodPayloadKind.OPAQUE
    else:
        definition = MHOD_DEFINITIONS[mhod_type]
        payload = typed_chunk.payload
        body_marker = (
            payload.child.generic_header.header_marker
            if isinstance(payload, MhodContainerPayload)
            else payload.data[:4]
            if isinstance(payload, MhodOpaquePayload)
            else b""
        )
        payload_kind = definition.payload_kind_for_parent(
            parent_marker,
            body_marker=body_marker,
        )
    validate_mhod_body_representation(typed_chunk, payload_kind, definition)

    if typed_chunk.raw_header:
        original_data = typed_chunk.raw_header + typed_chunk.raw_body
        original_header = parse_binary_struct(
            original_data,
            0,
            MhodHeader,
            limit=len(typed_chunk.raw_header),
        )
        if (
            typed_chunk.header.mhod_type == original_header.mhod_type
            and typed_chunk.header.padding_length == original_header.padding_length
            and typed_chunk.prefix == typed_chunk.original_prefix
            and typed_chunk.payload == typed_chunk.original_payload
        ):
            return typed_chunk.raw_body, typed_chunk.header

    return encode_mhod_body(
        typed_chunk,
        payload_kind,
        definition,
        serialize_child,
    )
