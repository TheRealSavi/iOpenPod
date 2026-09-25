from iPodDB.PhotosDB.parser.parser_definition import PARSER_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.shared.chunk import DatabaseDocument
from iPodDB.shared.chunk_reader import parse_database


def parse_PhotosDB(data: bytes | bytearray) -> DatabaseDocument[MhfdHeader]:
    """Parse a Photo Database through its sole typed database definition.

    Raises:
        iPodDBParseError: The bytes violate the PhotosDB structural definition.
    """

    return parse_database(data, PARSER_DEFINITION)
