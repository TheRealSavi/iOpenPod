"""Evidence-bounded ArtworkDB repairs, separate from lossless parsing."""

from dataclasses import dataclass

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.parser.parser_definition import PARSER_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.ArtworkDB.shared.constants import ArtworkDatasetType
from iPodDB.shared.chunk import DatabaseDocument
from iPodDB.shared.image_list_repair import ImageListCountRepair as ArtworkDBCountRepair
from iPodDB.shared.image_list_repair import repair_image_list_counts

__all__ = ["ArtworkDBCountRepair", "ArtworkDBRepairResult", "repair_ArtworkDB"]


@dataclass(frozen=True, slots=True)
class ArtworkDBRepairResult:
    """Corrected candidate bytes and their normal typed parse, without file I/O."""

    data: bytes
    document: DatabaseDocument[MhfdHeader]
    repairs: tuple[ArtworkDBCountRepair, ...]


def repair_ArtworkDB(data: bytes | bytearray) -> ArtworkDBRepairResult:
    """Recover wrong MHLI counts while preserving every other source byte.

    Only complete, independently bounded MHII records authorize a correction.
    Callers retain the original source for lossless reads and publish repairs
    through their normal verified writing workflow.
    """
    result = repair_image_list_counts(
        data,
        parser_definition=PARSER_DEFINITION,
        parse=parse_ArtworkDB,
        image_dataset_type=ArtworkDatasetType.IMAGE_LIST,
        image_definition=MHII_DEFINITION,
        image_identity=lambda header: header.image_id,
    )
    return ArtworkDBRepairResult(result.data, result.document, result.repairs)
