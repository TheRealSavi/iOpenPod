"""PhotosDB parser definition assembled from shared format definitions."""

from collections.abc import Mapping
from types import MappingProxyType

from iPodDB.PhotosDB.parser.mhod_payload_spec_registry import MHOD_PAYLOAD_SPECS
from iPodDB.PhotosDB.shared.constants import MhodPayloadKind
from iPodDB.PhotosDB.shared.database_definition import DATABASE_DEFINITION
from iPodDB.PhotosDB.shared.mhod_payload_spec_registry import MHOD_DEFINITIONS
from iPodDB.shared.types import DatabaseParserDefinition, MhodSpec, MHODTypeID

_MHOD_SPECS: Mapping[MHODTypeID, MhodSpec] = MappingProxyType(
    {
        MHODTypeID(int(mhod_type)): MhodSpec(
            definition.name,
            MHOD_PAYLOAD_SPECS[definition.payload_kind],
        )
        for mhod_type, definition in MHOD_DEFINITIONS.items()
    }
)

PARSER_DEFINITION = DatabaseParserDefinition(
    database=DATABASE_DEFINITION,
    mhod_specs=_MHOD_SPECS,
    unknown_mhod_spec=MhodSpec(
        "Unknown PhotosDB MHOD",
        MHOD_PAYLOAD_SPECS[MhodPayloadKind.OPAQUE],
    ),
)
