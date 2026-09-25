"""Lossless, definition-driven iTunesDB serialization."""

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind
from iPodDB.iTunesDB.shared.database_definition import DATABASE_DEFINITION
from iPodDB.iTunesDB.shared.mhod_payload_spec_registry import MHOD_DEFINITIONS
from iPodDB.iTunesDB.writer.mhod_encoder import (
    encode_mhod_body,
    validate_mhod_body_representation,
)
from iPodDB.shared.binary_struct import parse_binary_struct
from iPodDB.shared.chunk import (
    ChunkHeader,
    DatabaseDocument,
    ParsedChunk,
    chunk_as,
)
from iPodDB.shared.chunk_writer import NestedChunkSerializer, serialize_database


def _serialize_mhod_body(
    chunk: ParsedChunk[ChunkHeader],
    parent_marker: bytes | None,
    serialize_child: NestedChunkSerializer,
) -> tuple[bytes, ChunkHeader]:
    del serialize_child
    typed_chunk = chunk_as(chunk, MhodHeader)

    definition = MHOD_DEFINITIONS.get(typed_chunk.header.mhod_type)
    payload_kind = (
        MhodPayloadKind.OPAQUE
        if definition is None
        else definition.payload_kind_for_parent(parent_marker)
    )
    validate_mhod_body_representation(typed_chunk, payload_kind)

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
            and typed_chunk.prefix == typed_chunk.original_prefix
            and typed_chunk.payload == typed_chunk.original_payload
        ):
            return typed_chunk.raw_body, typed_chunk.header

    return encode_mhod_body(typed_chunk, payload_kind)


def write_iTunesDB(database: DatabaseDocument[MhbdHeader]) -> bytes:
    """Serialize an iTunesDB through the shared definition-driven writer.

    Raises:
        iPodDBWriteError: The Chunk tree cannot be serialized losslessly.
        TypeError: A Chunk uses a header or payload representation of the wrong type.
    """
    return serialize_database(
        database,
        DATABASE_DEFINITION,
        _serialize_mhod_body,
    )
