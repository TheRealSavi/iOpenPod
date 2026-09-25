from iPodDB.ArtworkDB.parser.parser_definition import PARSER_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.shared.chunk import DatabaseDocument
from iPodDB.shared.chunk_reader import parse_database


def parse_ArtworkDB(data: bytes | bytearray) -> DatabaseDocument[MhfdHeader]:
    """Parse an ArtworkDB through its sole typed database definition.

    Raises:
        iPodDBParseError: The bytes violate the ArtworkDB structural definition.
    """

    return parse_database(data, PARSER_DEFINITION)
