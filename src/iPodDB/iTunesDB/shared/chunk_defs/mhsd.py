from dataclasses import dataclass

from iPodDB.iTunesDB.shared.chunk_defs.mhla import DEFINITION as MHLA_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhli import DEFINITION as MHLI_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhlp import DEFINITION as MHLP_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT_DEFINITION
from iPodDB.shared.chunk import MhsdChunkHeader
from iPodDB.shared.chunk_field import chunk_field as cf
from iPodDB.shared.types import (
    ChunkDefinition,
    MhsdDatasetDefinition,
    MhsdDatasetSpec,
    OpaqueMhsdDatasetDefinition,
)


@dataclass(frozen=True, slots=True)
class MhsdHeader(MhsdChunkHeader):
    dataset_type: int = cf(0x0C, "u32")


DEFINITION: ChunkDefinition[MhsdHeader] = ChunkDefinition(
    marker=b"mhsd",
    purpose="iTunesDB dataset wrapper",
    header_type=MhsdHeader,
    minimum_header_size=16,
    header_sizes=(96,),
    extent_type="length",
    body_kind="dataset",
    child_marker_groups=(),
)

DATASET_DEFINITIONS: tuple[MhsdDatasetSpec, ...] = (
    MhsdDatasetDefinition(1, "Track list", MHLT_DEFINITION),
    MhsdDatasetDefinition(2, "Playlist list", MHLP_DEFINITION),
    MhsdDatasetDefinition(3, "Podcast playlist list", MHLP_DEFINITION),
    MhsdDatasetDefinition(4, "Album list", MHLA_DEFINITION),
    MhsdDatasetDefinition(5, "Smart playlist list", MHLP_DEFINITION),
    MhsdDatasetDefinition(6, "Unknown track-list dataset", MHLT_DEFINITION),
    OpaqueMhsdDatasetDefinition(7, "Reserved iTunesDB data"),
    MhsdDatasetDefinition(8, "Artist list", MHLI_DEFINITION),
    OpaqueMhsdDatasetDefinition(9, "Genius CUID data"),
    MhsdDatasetDefinition(10, "Unknown track-list dataset", MHLT_DEFINITION),
)
