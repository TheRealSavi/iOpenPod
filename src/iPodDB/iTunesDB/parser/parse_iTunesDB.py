from iPodDB.iTunesDB.cdb import is_iTunesCDB
from iPodDB.iTunesDB.parser.parser_definition import PARSER_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.shared.chunk import DatabaseDocument
from iPodDB.shared.chunk_reader import parse_database
from iPodDB.shared.diagnostics import log_unknown_data


@log_unknown_data("iTunesDB")
def parse_iTunesDB(data: bytes | bytearray) -> DatabaseDocument[MhbdHeader]:
    """Parse one logical iTunesDB through the shared database definition.

    Physical iTunesCDB framing is an explicit codec boundary. Callers handling
    that artifact must first use :func:`decompress_iTunesCDB` and pass its
    ``logical_bytes`` here. This keeps the parser/writer pairing symmetric:
    ``write_iTunesDB(parse_iTunesDB(data))`` always produces logical bytes.

    Raises:
        iPodDBParseError: The bytes violate the iTunesDB structural definition.
    """
    if is_iTunesCDB(data):
        raise ValueError(
            "parse_iTunesDB accepts logical bytes; decompress iTunesCDB framing first."
        )
    return parse_database(data, PARSER_DEFINITION)
