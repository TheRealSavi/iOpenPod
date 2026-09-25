"""MHSD (Photo Database dataset) Chunk definition."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhla import DEFINITION as MHLA_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhlf import DEFINITION as MHLF_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhli import DEFINITION as MHLI_DEFINITION
from iPodDB.PhotosDB.shared.constants import PhotosDatasetType
from iPodDB.shared.types import (
    ChunkDefinition,
    MhsdDatasetDefinition,
    MhsdDatasetSpec,
)

DEFINITION: ChunkDefinition[MhsdHeader] = ChunkDefinition(
    marker=b"mhsd",
    purpose="Photo Database dataset wrapper",
    header_type=MhsdHeader,
    minimum_header_size=14,
    header_sizes=(96,),
    extent_type="length",
    body_kind="dataset",
    child_marker_groups=(),
)

DATASET_DEFINITIONS: tuple[MhsdDatasetSpec, ...] = (
    MhsdDatasetDefinition(
        dataset_type=PhotosDatasetType.IMAGE_LIST,
        purpose="Photo image list",
        child_definition=MHLI_DEFINITION,
    ),
    MhsdDatasetDefinition(
        dataset_type=PhotosDatasetType.PHOTO_ALBUM_LIST,
        purpose="Photo album list",
        child_definition=MHLA_DEFINITION,
    ),
    MhsdDatasetDefinition(
        dataset_type=PhotosDatasetType.FILE_LIST,
        purpose="Photo file-format list",
        child_definition=MHLF_DEFINITION,
    ),
)

__all__ = ["DATASET_DEFINITIONS", "DEFINITION", "MhsdHeader"]
