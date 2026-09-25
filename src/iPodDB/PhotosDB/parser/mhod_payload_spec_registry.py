"""Parser functions selected by shared Photo Database MHOD definitions."""

from collections.abc import Mapping
from types import MappingProxyType

from iPodDB.PhotosDB.parser.mhod_parsers.container_mhod import (
    parse_container_payload,
)
from iPodDB.PhotosDB.parser.mhod_parsers.opaque_mhod import parse_opaque_payload
from iPodDB.PhotosDB.parser.mhod_parsers.string_mhod import parse_string_payload
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPrefix,
)
from iPodDB.PhotosDB.shared.constants import MhodPayloadKind, PhotosMhodType
from iPodDB.PhotosDB.shared.mhod_payload_spec_registry import MHOD_DEFINITIONS
from iPodDB.shared.types import (
    ContextualMhodPayloadSpec,
    MhodPayloadSpec,
    MhodPayloadSpecSelectionContext,
    contextual_mhod_payload_spec,
    prefixed_mhod_payload_spec,
    unprefixed_mhod_payload_spec,
)

OPAQUE_SPEC = unprefixed_mhod_payload_spec(parse_opaque_payload)
STRING_SPEC = prefixed_mhod_payload_spec(
    MhodStringPrefix,
    parse_string_payload,
    prefix_origin="payload",
)
CONTAINER_SPEC = unprefixed_mhod_payload_spec(parse_container_payload)


def _resolve_contextual_payload(
    context: MhodPayloadSpecSelectionContext,
) -> MhodPayloadSpec:
    try:
        mhod_type = PhotosMhodType(int(context.mhod_type))
    except ValueError:
        return OPAQUE_SPEC
    definition = MHOD_DEFINITIONS[mhod_type]
    parent_marker = (
        context.ancestors[-1].generic_header.header_marker
        if context.ancestors
        else None
    )
    payload_kind = definition.payload_kind_for_parent(
        parent_marker,
        body_marker=bytes(
            context.data[
                context.header_end : min(context.header_end + 4, context.chunk_end)
            ]
        ),
    )
    if payload_kind == MhodPayloadKind.STRING:
        return STRING_SPEC
    if payload_kind == MhodPayloadKind.CONTAINER:
        return CONTAINER_SPEC
    return OPAQUE_SPEC


CONTEXTUAL_THUMBNAIL_SPEC = contextual_mhod_payload_spec(_resolve_contextual_payload)

MHOD_PAYLOAD_SPECS: Mapping[
    MhodPayloadKind,
    MhodPayloadSpec | ContextualMhodPayloadSpec,
] = MappingProxyType(
    {
        MhodPayloadKind.OPAQUE: OPAQUE_SPEC,
        MhodPayloadKind.STRING: STRING_SPEC,
        MhodPayloadKind.CONTAINER: CONTAINER_SPEC,
        MhodPayloadKind.CONTEXTUAL_THUMBNAIL: CONTEXTUAL_THUMBNAIL_SPEC,
        MhodPayloadKind.CONTEXTUAL_AUXILIARY: CONTEXTUAL_THUMBNAIL_SPEC,
    }
)
