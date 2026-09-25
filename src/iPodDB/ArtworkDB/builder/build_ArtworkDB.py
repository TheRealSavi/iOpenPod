"""Definition-driven construction of new ArtworkDB Chunks and databases."""

from typing import cast

from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import DEFINITION as MHFD_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    EMPTY_MHAF_BODY,
    MhodOpaquePayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import DEFINITION as MHSD_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.ArtworkDB.shared.constants import (
    ArtworkDatasetType,
    ArtworkMhodType,
    MhodPayloadKind,
)
from iPodDB.ArtworkDB.shared.database_definition import DATABASE_DEFINITION
from iPodDB.ArtworkDB.shared.mhod_payload_spec_registry import MHOD_DEFINITIONS
from iPodDB.shared.chunk import (
    ChunkHeader,
    ChunkPayload,
    DatabaseDocument,
    EmptyChunkHeader,
    MhodPayloadPrefix,
    ParsedChunk,
)
from iPodDB.shared.chunk_builder import new_chunk
from iPodDB.shared.types import ChunkDefinition, MhsdDatasetDefinition


def new_artwork_chunk[H: ChunkHeader](
    definition: ChunkDefinition[H],
    header: H,
    *,
    children: tuple[ParsedChunk[ChunkHeader], ...] = (),
    prefix: MhodPayloadPrefix | None = None,
    payload: ChunkPayload | None = None,
) -> ParsedChunk[H]:
    """Construct a writable Chunk from a registered ArtworkDB definition."""

    return new_chunk(
        DATABASE_DEFINITION,
        definition,
        header,
        children=children,
        prefix=prefix,
        payload=payload,
    )


def new_string_mhod(
    mhod_type: ArtworkMhodType,
    value: str,
    *,
    encoding_indicator: int | None = None,
) -> ParsedChunk[MhodHeader]:
    """Construct a writable ArtworkDB string MHOD."""

    mhod_type = ArtworkMhodType(mhod_type)
    definition = MHOD_DEFINITIONS[mhod_type]
    if MhodPayloadKind.STRING not in definition.supported_payload_kinds:
        raise ValueError(
            f"MHOD type {int(mhod_type)} does not support a string payload"
        )
    if encoding_indicator is None:
        encoding_indicator = definition.default_string_encoding_indicator
    if encoding_indicator is None:
        raise ValueError(f"MHOD type {int(mhod_type)} has no string encoding default")
    return new_artwork_chunk(
        MHOD_DEFINITION,
        MhodHeader(mhod_type=mhod_type),
        prefix=MhodStringPrefix(
            string_byte_length=0,
            encoding_indicator=encoding_indicator,
        ),
        payload=MhodStringPayload(
            value=value,
            raw_value=b"",
            trailing_data=b"",
        ),
    )


def new_container_mhod(
    mhod_type: ArtworkMhodType,
    child: ParsedChunk[MhniHeader],
) -> ParsedChunk[MhodHeader]:
    """Construct a writable ArtworkDB MHOD containing one MHNI Chunk."""

    mhod_type = ArtworkMhodType(mhod_type)
    definition = MHOD_DEFINITIONS[mhod_type]
    if MhodPayloadKind.CONTAINER not in definition.supported_payload_kinds:
        raise ValueError(
            f"MHOD type {int(mhod_type)} does not support a container payload"
        )
    child_definition = definition.container_child_definition
    if (
        child_definition is None
        or child.generic_header.header_marker != child_definition.marker
        or type(child.header) is not child_definition.header_type
    ):
        expected_marker = (
            child_definition.marker if child_definition is not None else b"<none>"
        )
        raise ValueError(
            f"MHOD type {int(mhod_type)} container child must use {expected_marker!r}"
        )
    return new_artwork_chunk(
        MHOD_DEFINITION,
        MhodHeader(mhod_type=mhod_type),
        payload=MhodContainerPayload(child=child, trailing_data=b""),
    )


def new_auxiliary_mhod() -> ParsedChunk[MhodHeader]:
    """Construct the evidenced empty MHAF body inside a type-6 MHOD."""
    return new_artwork_chunk(
        MHOD_DEFINITION,
        MhodHeader(mhod_type=ArtworkMhodType.UNKNOWN_CONTAINER_6),
        payload=MhodOpaquePayload(EMPTY_MHAF_BODY),
    )


def new_ArtworkDB(
    *,
    next_mhii_id: int,
    unk_mhfd_0x10: int,
    image_items: tuple[ParsedChunk[ChunkHeader], ...] = (),
    photo_albums: tuple[ParsedChunk[ChunkHeader], ...] = (),
    file_items: tuple[ParsedChunk[ChunkHeader], ...] = (),
) -> DatabaseDocument[MhfdHeader]:
    """Construct a complete ArtworkDB with explicit device-specific root values."""

    if not 0 <= next_mhii_id <= 0xFFFFFFFF:
        raise ValueError("next_mhii_id must fit an unsigned 32-bit field")
    if not 0 <= unk_mhfd_0x10 <= 0xFFFFFFFF:
        raise ValueError("unk_mhfd_0x10 must fit an unsigned 32-bit field")

    items_by_dataset = {
        ArtworkDatasetType.IMAGE_LIST: image_items,
        ArtworkDatasetType.PHOTO_ALBUM_LIST: photo_albums,
        ArtworkDatasetType.FILE_LIST: file_items,
    }
    datasets: list[ParsedChunk[ChunkHeader]] = []
    for dataset_definition in DATABASE_DEFINITION.mhsd_dataset_definitions:
        if not isinstance(dataset_definition, MhsdDatasetDefinition):
            raise TypeError("ArtworkDB datasets must have structured definitions")
        dataset_type = ArtworkDatasetType(dataset_definition.dataset_type)
        list_chunk = new_artwork_chunk(
            dataset_definition.child_definition,
            EmptyChunkHeader(),
            children=items_by_dataset[dataset_type],
        )
        datasets.append(
            new_artwork_chunk(
                MHSD_DEFINITION,
                MhsdHeader(dataset_type=dataset_type),
                children=(cast("ParsedChunk[ChunkHeader]", list_chunk),),
            )
        )

    return new_artwork_chunk(
        MHFD_DEFINITION,
        MhfdHeader(
            unk_mhfd_0x10=unk_mhfd_0x10,
            next_mhii_id=next_mhii_id,
        ),
        children=tuple(datasets),
    )
