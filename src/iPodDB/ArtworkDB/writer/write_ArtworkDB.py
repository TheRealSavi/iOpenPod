"""Lossless, definition-driven ArtworkDB serialization."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.database_definition import DATABASE_DEFINITION
from iPodDB.ArtworkDB.writer.mhod_serializer import (
    serialize_artwork_mhod_body,
)
from iPodDB.shared.chunk import DatabaseDocument
from iPodDB.shared.chunk_writer import serialize_database


def write_ArtworkDB(database: DatabaseDocument[MhfdHeader]) -> bytes:
    """Serialize an ArtworkDB through the shared definition-driven writer.

    Raises:
        iPodDBWriteError: The Chunk tree cannot be serialized losslessly.
        TypeError: A Chunk uses a header or payload representation of the wrong type.
    """

    return serialize_database(
        database,
        DATABASE_DEFINITION,
        serialize_artwork_mhod_body,
    )
