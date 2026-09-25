"""MHSD (ArtworkDB dataset) Chunk definition."""

from dataclasses import dataclass

from iPodDB.ArtworkDB.shared.chunk_defs.mhla import DEFINITION as MHLA_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhlf import DEFINITION as MHLF_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhli import DEFINITION as MHLI_DEFINITION
from iPodDB.ArtworkDB.shared.constants import ArtworkDatasetType
from iPodDB.shared.chunk import MhsdChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import (
    ChunkDefinition,
    MhsdDatasetDefinition,
    MhsdDatasetSpec,
)


@dataclass(frozen=True, slots=True)
class MhsdHeader(MhsdChunkHeader):
    dataset_type: int = cf(0x0C, "u16")
    unk_mhsd_0x0e: int = cf(0x0E, "u16")


DEFINITION: ChunkDefinition[MhsdHeader] = ChunkDefinition(
    marker=b"mhsd",
    purpose="ArtworkDB dataset wrapper",
    header_type=MhsdHeader,
    minimum_header_size=14,
    header_sizes=(96,),
    extent_type="length",
    body_kind="dataset",
    child_marker_groups=(),
)

DATASET_DEFINITIONS: tuple[MhsdDatasetSpec, ...] = (
    MhsdDatasetDefinition(
        dataset_type=ArtworkDatasetType.IMAGE_LIST,
        purpose="Artwork image list",
        child_definition=MHLI_DEFINITION,
    ),
    MhsdDatasetDefinition(
        dataset_type=ArtworkDatasetType.PHOTO_ALBUM_LIST,
        purpose="Photo album list",
        child_definition=MHLA_DEFINITION,
    ),
    MhsdDatasetDefinition(
        dataset_type=ArtworkDatasetType.FILE_LIST,
        purpose="Artwork file-format list",
        child_definition=MHLF_DEFINITION,
    ),
)
