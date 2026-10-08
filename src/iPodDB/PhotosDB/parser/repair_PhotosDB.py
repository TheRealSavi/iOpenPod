"""Evidence-bounded PhotosDB repairs, separate from lossless parsing."""

from dataclasses import dataclass

from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.parser.parser_definition import PARSER_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.PhotosDB.shared.constants import PhotosDatasetType
from iPodDB.shared.chunk import DatabaseDocument
from iPodDB.shared.image_list_repair import ImageListCountRepair as PhotosDBCountRepair
from iPodDB.shared.image_list_repair import repair_image_list_counts

__all__ = ["PhotosDBCountRepair", "PhotosDBRepairResult", "repair_PhotosDB"]


@dataclass(frozen=True, slots=True)
class PhotosDBRepairResult:
    """Corrected candidate bytes and their nominal PhotosDB parse, without I/O."""

    data: bytes
    document: DatabaseDocument[MhfdHeader]
    repairs: tuple[PhotosDBCountRepair, ...]


def repair_PhotosDB(data: bytes | bytearray) -> PhotosDBRepairResult:
    """Recover wrong MHLI counts without rebuilding photos, albums or thumbnails.

    Callers retain the original source for unchanged serialization; this result
    is a candidate for the ordinary verified publication workflow.
    """
    result = repair_image_list_counts(
        data,
        parser_definition=PARSER_DEFINITION,
        parse=parse_PhotosDB,
        image_dataset_type=PhotosDatasetType.IMAGE_LIST,
        image_definition=MHII_DEFINITION,
        image_identity=lambda header: header.image_id,
    )
    return PhotosDBRepairResult(result.data, result.document, result.repairs)
