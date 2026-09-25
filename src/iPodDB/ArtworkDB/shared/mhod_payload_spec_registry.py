from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from iPodDB.ArtworkDB.shared.chunk_defs.mhba import DEFINITION as MHBA_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import DEFINITION as MHNI_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.constants import ArtworkMhodType, MhodPayloadKind
from iPodDB.shared.types import ChunkDefinition


@dataclass(frozen=True, slots=True)
class ArtworkMhodDefinition:
    """Known meaning and payload shape for one ArtworkDB MHOD type."""

    mhod_type: ArtworkMhodType
    name: str
    payload_kind: MhodPayloadKind
    default_string_encoding_indicator: int | None = None
    contextual_string_parent_markers: frozenset[bytes] = frozenset()
    container_child_definition: ChunkDefinition[MhniHeader] | None = None

    def payload_kind_for_parent(
        self, parent_marker: bytes | None, *, body_marker: bytes = b""
    ) -> MhodPayloadKind:
        """Resolve contextual payload layouts without parser-specific knowledge."""
        if self.payload_kind == MhodPayloadKind.CONTEXTUAL_AUXILIARY:
            return (
                MhodPayloadKind.CONTAINER
                if body_marker == MHNI_DEFINITION.marker
                else MhodPayloadKind.OPAQUE
            )
        if self.payload_kind != MhodPayloadKind.CONTEXTUAL_THUMBNAIL:
            return self.payload_kind
        if parent_marker in self.contextual_string_parent_markers:
            return MhodPayloadKind.STRING
        return MhodPayloadKind.CONTAINER

    @property
    def supported_payload_kinds(self) -> frozenset[MhodPayloadKind]:
        if self.payload_kind == MhodPayloadKind.CONTEXTUAL_AUXILIARY:
            return frozenset({MhodPayloadKind.CONTAINER, MhodPayloadKind.OPAQUE})
        if self.payload_kind == MhodPayloadKind.CONTEXTUAL_THUMBNAIL:
            return frozenset({MhodPayloadKind.STRING, MhodPayloadKind.CONTAINER})
        return frozenset({self.payload_kind})


MHOD_DEFINITIONS: Mapping[ArtworkMhodType, ArtworkMhodDefinition] = MappingProxyType(
    {
        ArtworkMhodType.ALBUM_NAME: ArtworkMhodDefinition(
            ArtworkMhodType.ALBUM_NAME,
            "Album Name",
            MhodPayloadKind.STRING,
            default_string_encoding_indicator=1,
        ),
        ArtworkMhodType.THUMBNAIL_IMAGE: ArtworkMhodDefinition(
            ArtworkMhodType.THUMBNAIL_IMAGE,
            "Thumbnail Image",
            MhodPayloadKind.CONTEXTUAL_THUMBNAIL,
            default_string_encoding_indicator=1,
            contextual_string_parent_markers=frozenset({MHBA_DEFINITION.marker}),
            container_child_definition=MHNI_DEFINITION,
        ),
        ArtworkMhodType.FILE_NAME: ArtworkMhodDefinition(
            ArtworkMhodType.FILE_NAME,
            "File Name",
            MhodPayloadKind.STRING,
            default_string_encoding_indicator=2,
        ),
        ArtworkMhodType.UNKNOWN_4: ArtworkMhodDefinition(
            ArtworkMhodType.UNKNOWN_4,
            "Unknown (MHOD 4)",
            MhodPayloadKind.OPAQUE,
        ),
        ArtworkMhodType.FULL_RES_IMAGE: ArtworkMhodDefinition(
            ArtworkMhodType.FULL_RES_IMAGE,
            "Full Res Image",
            MhodPayloadKind.CONTAINER,
            container_child_definition=MHNI_DEFINITION,
        ),
        ArtworkMhodType.UNKNOWN_CONTAINER_6: ArtworkMhodDefinition(
            ArtworkMhodType.UNKNOWN_CONTAINER_6,
            "Unknown Image Container (MHOD 6)",
            MhodPayloadKind.CONTEXTUAL_AUXILIARY,
            container_child_definition=MHNI_DEFINITION,
        ),
    }
)
