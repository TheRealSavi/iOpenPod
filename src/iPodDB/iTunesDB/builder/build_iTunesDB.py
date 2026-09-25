"""Definition-driven construction of new iTunesDB Chunks and databases."""

from typing import Literal

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import DEFINITION as MHBD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.url_mhod import MhodUrlPayload
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind, MhodType
from iPodDB.iTunesDB.shared.database_definition import DATABASE_DEFINITION
from iPodDB.iTunesDB.shared.mhod_payload_spec_registry import MHOD_DEFINITIONS
from iPodDB.shared.chunk import (
    ChunkHeader,
    ChunkPayload,
    DatabaseDocument,
    MhodPayloadPrefix,
    ParsedChunk,
)
from iPodDB.shared.chunk_builder import new_chunk
from iPodDB.shared.types import ChunkDefinition


def new_itunes_chunk[H: ChunkHeader](
    definition: ChunkDefinition[H],
    header: H,
    *,
    children: tuple[ParsedChunk[ChunkHeader], ...] = (),
    prefix: MhodPayloadPrefix | None = None,
    payload: ChunkPayload | None = None,
) -> ParsedChunk[H]:
    """Construct a writable Chunk from a registered iTunesDB definition."""

    return new_chunk(
        DATABASE_DEFINITION,
        definition,
        header,
        children=children,
        prefix=prefix,
        payload=payload,
    )


def new_string_mhod(
    mhod_type: int,
    value: str,
    *,
    encoding_indicator: Literal[1, 2] = 1,
) -> ParsedChunk[MhodHeader]:
    """Construct a writable UTF-16LE or UTF-8 iTunesDB string MHOD."""

    definition = MHOD_DEFINITIONS.get(mhod_type)
    if definition is None or definition.payload_kind != MhodPayloadKind.STRING:
        raise ValueError(f"MHOD type {mhod_type} does not support a string payload")
    return new_itunes_chunk(
        MHOD_DEFINITION,
        MhodHeader(mhod_type=mhod_type),
        prefix=MhodStringPrefix(encoding_indicator=encoding_indicator),
        payload=MhodStringPayload(value=value),
    )


def new_url_mhod(
    mhod_type: MhodType,
    value: str,
) -> ParsedChunk[MhodHeader]:
    """Construct a writable iTunesDB podcast URL MHOD."""

    definition = MHOD_DEFINITIONS[mhod_type]
    if definition.payload_kind != MhodPayloadKind.URL:
        raise ValueError(f"MHOD type {mhod_type} does not support a URL payload")
    return new_itunes_chunk(
        MHOD_DEFINITION,
        MhodHeader(mhod_type=mhod_type),
        payload=MhodUrlPayload(value=value),
    )


def new_iTunesDB(
    header: MhbdHeader,
    *,
    datasets: tuple[ParsedChunk[ChunkHeader], ...] = (),
) -> DatabaseDocument[MhbdHeader]:
    """Construct a complete iTunesDB from explicit root and dataset values."""

    return new_itunes_chunk(
        MHBD_DEFINITION,
        header,
        children=datasets,
    )
