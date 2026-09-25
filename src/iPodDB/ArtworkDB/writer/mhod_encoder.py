"""Typed inverse encoders for every understood ArtworkDB MHOD payload layout."""

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from iPodDB.ArtworkDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
    decode_artwork_string,
    encode_artwork_string,
)
from iPodDB.ArtworkDB.shared.constants import MhodPayloadKind
from iPodDB.ArtworkDB.shared.mhod_payload_spec_registry import ArtworkMhodDefinition
from iPodDB.shared.binary_struct import (
    binary_struct_extent,
    parse_binary_struct,
    write_binary_struct_into,
)
from iPodDB.shared.chunk import MhodPayload, MhodPayloadPrefix, ParsedChunk
from iPodDB.shared.chunk_writer import NestedChunkSerializer

type MhodPayloadShape = tuple[
    type[MhodPayloadPrefix] | None,
    type[MhodPayload],
]

_PAYLOAD_SHAPES: Mapping[MhodPayloadKind, MhodPayloadShape] = MappingProxyType(
    {
        MhodPayloadKind.STRING: (MhodStringPrefix, MhodStringPayload),
        MhodPayloadKind.CONTAINER: (None, MhodContainerPayload),
        MhodPayloadKind.OPAQUE: (None, MhodOpaquePayload),
    }
)


def validate_mhod_body_representation(
    chunk: ParsedChunk[MhodHeader],
    payload_kind: MhodPayloadKind,
    definition: ArtworkMhodDefinition | None,
) -> None:
    """Require the one prefix/payload representation for a concrete MHOD kind."""

    shape = _PAYLOAD_SHAPES.get(payload_kind)
    if shape is None:
        raise ValueError(f"MHOD payload kind {payload_kind.value} is not concrete")

    prefix_type, payload_type = shape
    prefix_is_valid = (
        chunk.prefix is None
        if prefix_type is None
        else type(chunk.prefix) is prefix_type
    )
    if not prefix_is_valid or type(chunk.payload) is not payload_type:
        raise ValueError(
            f"MHOD type {chunk.header.mhod_type} requires a "
            f"{payload_kind.value} payload representation"
        )

    if isinstance(chunk.payload, MhodContainerPayload):
        child_definition = (
            None if definition is None else definition.container_child_definition
        )
        child = chunk.payload.child
        if (
            child_definition is None
            or child.generic_header.header_marker != child_definition.marker
            or type(child.header) is not child_definition.header_type
        ):
            expected_marker = (
                child_definition.marker if child_definition is not None else b"<none>"
            )
            raise ValueError(
                f"MHOD type {chunk.header.mhod_type} container child must use "
                f"{expected_marker!r}"
            )


def _encode_string(
    chunk: ParsedChunk[MhodHeader],
) -> tuple[bytes, MhodHeader]:
    prefix = chunk.prefix_as(MhodStringPrefix)
    payload = chunk.payload_as(MhodStringPayload)
    prefix_end = binary_struct_extent(MhodStringPrefix)
    if chunk.raw_header:
        original_header = parse_binary_struct(
            chunk.raw_header,
            0,
            MhodHeader,
            limit=len(chunk.raw_header),
        )
        original_prefix = parse_binary_struct(
            chunk.raw_body,
            0,
            MhodStringPrefix,
            limit=len(chunk.raw_body),
        )
        unchanged_value = (
            prefix == original_prefix
            and payload.value
            == decode_artwork_string(
                payload.raw_value,
                original_prefix.encoding_indicator,
            )
        )
        prefix_bytes = bytearray(chunk.raw_body[:prefix_end])
    else:
        original_header = MhodHeader(mhod_type=chunk.header.mhod_type)
        unchanged_value = False
        prefix_bytes = bytearray(prefix_end)

    if unchanged_value:
        encoded = payload.raw_value
        trailing_data = payload.trailing_data
        header = replace(
            chunk.header,
            padding_length=original_header.padding_length,
        )
    else:
        encoded = encode_artwork_string(payload.value, prefix.encoding_indicator)
        padding_length = (4 - len(encoded) % 4) % 4
        retained_suffix = payload.trailing_data[
            min(original_header.padding_length, len(payload.trailing_data)) :
        ]
        trailing_data = bytes(padding_length) + retained_suffix
        header = replace(chunk.header, padding_length=padding_length)

    encoded_prefix = replace(prefix, string_byte_length=len(encoded))
    write_binary_struct_into(prefix_bytes, encoded_prefix, limit=prefix_end)
    body = bytes(prefix_bytes) + encoded + trailing_data
    return body, header


def _encode_container(
    chunk: ParsedChunk[MhodHeader],
    serialize_child: NestedChunkSerializer,
) -> tuple[bytes, MhodHeader]:
    payload = chunk.payload_as(MhodContainerPayload)
    body = serialize_child(payload.child, MHOD_DEFINITION.marker)
    return body + payload.trailing_data, chunk.header


def _encode_opaque(
    chunk: ParsedChunk[MhodHeader],
) -> tuple[bytes, MhodHeader]:
    return chunk.payload_as(MhodOpaquePayload).data, chunk.header


def encode_mhod_body(
    chunk: ParsedChunk[MhodHeader],
    payload_kind: MhodPayloadKind,
    definition: ArtworkMhodDefinition | None,
    serialize_child: NestedChunkSerializer,
) -> tuple[bytes, MhodHeader]:
    """Encode one changed MHOD body through its mandatory typed inverse."""

    validate_mhod_body_representation(chunk, payload_kind, definition)
    if payload_kind == MhodPayloadKind.STRING:
        return _encode_string(chunk)
    if payload_kind == MhodPayloadKind.CONTAINER:
        return _encode_container(chunk, serialize_child)
    if payload_kind == MhodPayloadKind.OPAQUE:
        return _encode_opaque(chunk)
    raise ValueError(f"MHOD payload kind {payload_kind.value} has no concrete encoder")
