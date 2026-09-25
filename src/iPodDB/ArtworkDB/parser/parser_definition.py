"""ArtworkDB parser definition assembled from shared format definitions."""

from collections.abc import Mapping
from types import MappingProxyType

from iPodDB.ArtworkDB.parser.mhod_payload_spec_registry import (
    MHOD_PAYLOAD_SPECS,
)
from iPodDB.ArtworkDB.shared.constants import MhodPayloadKind
from iPodDB.ArtworkDB.shared.database_definition import DATABASE_DEFINITION
from iPodDB.ArtworkDB.shared.mhod_payload_spec_registry import MHOD_DEFINITIONS
from iPodDB.shared.types import DatabaseParserDefinition, MhodSpec, MHODTypeID

_MHOD_SPECS: Mapping[MHODTypeID, MhodSpec] = MappingProxyType(
    {
        MHODTypeID(mhod_type): MhodSpec(
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
        "Unknown ArtworkDB MHOD",
        MHOD_PAYLOAD_SPECS[MhodPayloadKind.OPAQUE],
    ),
)
